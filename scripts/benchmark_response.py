"""Measure local response latency with synthetic input. No actions or microphone.

Stop other Jarvis model processes first on memory-constrained machines.
"""
import argparse
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from Backend.Config import Config
from Backend.LocalBrain import LocalBrain
from Backend.ReplyStream import spoken_boundary

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--mode",choices=("chat","voice"),required=True)
parser.add_argument("--output",type=Path,required=True)
args=parser.parse_args()
report={}
if args.mode=="chat":
    from llama_cpp import Llama
    loads=[]
    def load(**kwargs):
        start=time.perf_counter(); model=Llama(**kwargs,seed=42)
        loads.append(time.perf_counter()-start); return model
    brain=LocalBrain(Config()); results=[]
    with patch("llama_cpp.Llama",side_effect=load):
        for label in ("cold","warm"):
            started=time.perf_counter(); sample={"run":label,"first_text":None,"first_sentence":None}; pieces=[]
            def receive(piece):
                pieces.append(piece); elapsed=time.perf_counter()-started
                if sample["first_text"] is None: sample["first_text"]=elapsed
                if sample["first_sentence"] is None and spoken_boundary("".join(pieces)):
                    sample["first_sentence"]=elapsed
            answer=brain.reply("Explain how to organize my study time.",on_delta=receive)
            sample.update(complete=time.perf_counter()-started,text=answer)
            results.append(sample); print(json.dumps(sample),flush=True)
    report={"cold_includes_model_load":True,"model_load_seconds":loads,"threads":brain.config.settings.llm_threads,"results":results}
else:
    import numpy as np
    from faster_whisper.audio import decode_audio
    from Backend.VoiceInput import SpeechSegmenter, OfflineRecognizer, WakeGate
    from Backend.Commands import parse_command
    audio=decode_audio("artifacts/voice-validation/windows-voice-open-notepad.wav",sampling_rate=16000)
    rng=np.random.default_rng(42)
    fixtures=[("speech",np.concatenate((audio,np.zeros(32000,dtype=np.float32)))),
              ("steady_noise",rng.normal(0,.015,16000*16).astype(np.float32)),
              ("tone",(.05*np.sin(2*np.pi*220*np.arange(16000*16)/16000)).astype(np.float32))]
    results=[]; speech_chunk=None
    for name,samples in fixtures:
        pcm=(np.clip(samples,-1,1)*32767).astype(np.int16)
        for neural in (False,True):
            segmenter=SpeechSegmenter(neural=neural); endpoints=[]; start=time.perf_counter()
            for offset in range(0,len(pcm)-480,480):
                chunk=segmenter.feed(pcm[offset:offset+480].tobytes())
                if chunk:
                    endpoints.append(round((offset+480)/16000,3))
                    if name=="speech" and neural: speech_chunk=chunk
            results.append({"fixture":name,"neural":neural,"endpoints":endpoints,"processing_seconds":time.perf_counter()-start})
    assert speech_chunk is not None,"Speech was lost"
    recognizer=OfflineRecognizer(Config()); stamp=time.perf_counter()
    text=recognizer.transcribe(np.frombuffer(speech_chunk,dtype=np.int16).astype(np.float32)/32768.0)
    command=parse_command(WakeGate().accept(text))
    report={"fixtures":results,"stt_seconds_including_load":time.perf_counter()-stamp,"transcript":text,"action":command.action,"target":command.target}
    assert command.action=="open" and command.target.casefold()=="notepad",report
    print(json.dumps(report),flush=True)
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(report,indent=2),encoding="utf-8")
