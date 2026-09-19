"""Persistent CPU speech worker. Runtime network connections are disabled."""
import contextlib
import json
import os
import sys
import socket
import time
from pathlib import Path

def deny_network(*args, **kwargs):
    raise RuntimeError("Network access is disabled in the personal voice worker")


def main():
    channel = sys.stdout
    with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["DO_NOT_TRACK"] = "1"
        os.environ["OMP_NUM_THREADS"] = "2"
        socket.socket.connect = deny_network
        socket.socket.connect_ex = deny_network
        model = state = None
        loaded = None
        for line in sys.stdin:
            started = time.monotonic()
            try:
                data = json.loads(line)
                reference = Path(data["reference"])
                if not reference.is_file():
                    raise FileNotFoundError("Reference missing")
                os.environ["HF_HOME"] = str(Path(data["directory"]) / "voice/model/huggingface")
                import torch
                import numpy as np
                import sounddevice as sd
                from pocket_tts import TTSModel
                torch.set_num_threads(2)
                key = (str(reference), reference.stat().st_mtime_ns, data.get("model_config", ""))
                if model is None or loaded is None or loaded[2] != key[2]:
                    model = TTSModel.load_model(config=data["model_config"]) if data.get("model_config") else TTSModel.load_model()
                    if not model.has_voice_cloning:
                        raise RuntimeError("Installed weights do not support voice references")
                    state = None
                if state is None or key != loaded:
                    state = model.get_state_for_audio_prompt(str(reference))
                    loaded = key
                rate = round(model.sample_rate * 2 ** (data.get("speed", 0) / 20))
                volume = data.get("volume", 90) / 100
                first = None
                with torch.inference_mode(), sd.OutputStream(samplerate=rate, channels=1, dtype="float32") as output:
                    for chunk in model.generate_audio_stream(state, data["text"]):
                        pcm = np.clip(chunk.detach().cpu().numpy() * volume, -1, 1).astype("float32")
                        if first is None:
                            first = round((time.monotonic() - started) * 1000)
                        output.write(pcm.reshape(-1, 1))
                reply = {"ok": True, "first_audio_ms": first, "duration_ms": round((time.monotonic() - started) * 1000)}
            except Exception as exc:
                model = state = loaded = None
                reply = {"ok": False, "error": type(exc).__name__}
            channel.write(json.dumps(reply) + "\n")
            channel.flush()

if __name__ == "__main__":
    main()
