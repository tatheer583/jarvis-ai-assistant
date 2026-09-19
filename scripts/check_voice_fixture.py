"""Read a supplied WAV through local STT and the parser; never execute the plan."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import numpy as np
from faster_whisper.audio import decode_audio
from Backend.Config import Config
from Backend.VoiceInput import OfflineRecognizer, WakeGate
from Backend.Commands import parse_command
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('wav',type=Path)
parser.add_argument('--expect-action',required=True)
parser.add_argument('--expect-target',default='')
args=parser.parse_args()
recognizer=OfflineRecognizer(Config())
started=time.monotonic()
text=recognizer.transcribe(decode_audio(str(args.wav),sampling_rate=16000))
command=parse_command(WakeGate().accept(text))
print(json.dumps({'transcript':text,'action':command.action,'target':command.target,
    'seconds':round(time.monotonic()-started,2),'issue':recognizer.last_issue},ensure_ascii=True))
assert command.action==args.expect_action
assert command.target.casefold()==args.expect_target.casefold()
assert recognizer.transcribe(np.zeros(16000,dtype=np.float32))==''
assert recognizer.last_issue=='no_speech'
print('PASS: expected local voice plan and silence rejection; no action executed')
