"""Streaming adapter for Silero V6 bundled with faster-whisper 1.2.1.

No new download. Check the model schema so callers can fall back to WebRTC.
Recurrent state belongs to this stream, not the cached ONNX session.
"""
import numpy as np

class SpeechDetector:
    def __init__(self):
        from faster_whisper.vad import get_vad_model
        self.session = get_vad_model().session
        schema = {item.name: item.shape for item in self.session.get_inputs()}
        if (set(schema) != {"input", "h", "c"} or schema["input"][-1] != 576
                or schema["h"] != [1, 1, 128] or schema["c"] != [1, 1, 128]):
            raise RuntimeError("Unsupported bundled speech detector schema")
        self.reset()

    def reset(self):
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros_like(self.h)
        self.context = np.zeros(64, dtype=np.float32)
        self.pending = np.empty(0, dtype=np.float32)
        self.active = False

    def is_speech(self, frame):
        audio = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        self.pending = np.concatenate((self.pending, audio))
        while len(self.pending) >= 512:
            chunk, self.pending = self.pending[:512], self.pending[512:]
            output, self.h, self.c = self.session.run(None, {
                "input": np.concatenate((self.context, chunk))[None, :],
                "h": self.h, "c": self.c,
            })
            self.context = chunk[-64:].copy()
            probability = float(output.flat[0])
            self.active = probability >= (0.35 if self.active else 0.5)
        return self.active
