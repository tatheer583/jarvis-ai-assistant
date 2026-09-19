"""Verify packaged local-model streaming with an isolated, silent profile."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parent.parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--executable",type=Path)
parser.add_argument("--output",type=Path,required=True)
args=parser.parse_args()
models=Path(os.environ["LOCALAPPDATA"])/"Jarvis/models"
with tempfile.TemporaryDirectory(prefix="jarvis-stream-smoke-") as folder:
    Path(folder,"settings.json").write_text(json.dumps({
        "_schema_version":1,"search_roots":[],"listen_on_startup":False,"speech_enabled":False,
        "llm_path":str(models/"qwen2.5-1.5b-instruct-q4_k_m.gguf")
    }),encoding="utf-8")
    command=([str(args.executable.resolve()),"--engine","--no-listen"] if args.executable else\
             [sys.executable,"-B",str(ROOT/"Main.py"),"--engine","--no-listen"])
    process=subprocess.Popen(command,cwd=ROOT,
        env=dict(os.environ,JARVIS_DATA_DIR=folder,PYTHONIOENCODING="cp1252"),
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,encoding="utf-8",creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    packets=queue.Queue(); errors=[]
    def receive():
        for line in process.stdout:
            try: packets.put(json.loads(line))
            except ValueError: packets.put({"invalid_stdout":True})
    def stderr():
        for line in process.stderr:
            errors.append(line.rstrip()); del errors[:-20]
    threading.Thread(target=receive,daemon=True).start()
    threading.Thread(target=stderr,daemon=True).start()
    def send(value):
        process.stdin.write(json.dumps(value)+"\n");process.stdin.flush()
    def next_packet(timeout=120):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:
                packet=packets.get(timeout=.2)
                assert not packet.get("invalid_stdout"),"Invalid stdio"
                return packet
            except queue.Empty:
                if process.poll() is not None:
                    raise RuntimeError("Engine exited: "+" | ".join(errors))
        raise TimeoutError("Timed out: "+" | ".join(errors))
    try:
        while next_packet()["event"]!="ready": pass
        started=time.monotonic()
        send({"id":1,"op":"command","text":"Explain what RAM does."})
        first=None; complete=None; chunks=0; result=None; timing=None; final_messages=0
        deadline=started+180
        while time.monotonic()<deadline:
            packet=next_packet()
            kind,data=packet.get("event"),packet.get("data")
            if kind=="reply_progress" and data["content"].strip():
                first=first or time.monotonic()-started; chunks+=1
            if kind=="response_timing": timing=data
            if kind=="message" and data["role"]=="assistant":
                final_messages+=1;complete=time.monotonic()-started
            if kind=="result" and data["action"]=="chat": result=data
            if kind=="busy" and data is False and result: break
        assert result and result["success"],result
        assert first is not None and complete is not None and first<complete,(first,complete)
        assert chunks>1 and final_messages==1,(chunks,final_messages)
        assert timing and timing["first_text_ms"] is not None,timing
        send({"id":2,"op":"emergency"})
        while True:
            packet=next_packet()
            if packet["event"]=="response" and packet["data"].get("id")==2:
                assert packet["data"]["value"]["stopped"];break
        send({"op":"quit"});process.stdin.close();process.wait(timeout=15)
        assert process.returncode==0
        report={"first_visible_seconds":first,"complete_seconds":complete,
                "progress_events":chunks,"one_final_message":final_messages==1,
                "timing":timing,"answer":result["message"],"emergency":True,"exit_code":process.returncode,
                "profile":"temporary, microphone and speech disabled"}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2),encoding="utf-8")
        print(json.dumps(report),flush=True)
        print("PASS: local engine streams before completion; emergency and clean exit")
    finally:
        if process.poll() is None:
            process.terminate();process.wait(timeout=10)
        process.stdout.close();process.stderr.close()
