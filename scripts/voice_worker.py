"""Personal voice inference in a separate process; offline-only at runtime."""
import json
import os
import sys
from pathlib import Path

def main():
    data = json.load(sys.stdin)
    directory = Path(data["directory"])
    os.environ["HF_HOME"] = str(directory / "models/huggingface")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    import torch
    import sounddevice as sd
    from pocket_tts import TTSModel
    torch.set_num_threads(2)
    model = TTSModel.load_model()
    state = model.get_state_for_audio_prompt(data["reference"])
    with torch.inference_mode():
        audio = model.generate_audio(state, data["text"])
    sd.play(audio.detach().cpu().numpy(), model.sample_rate, blocking=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
