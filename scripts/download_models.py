"""Download public local models only when this setup command is explicitly run."""
import argparse
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", action="store_true", help="Prepare the optional local English personal-voice model")
    args = parser.parse_args()
    from Backend.Config import Config
    config = Config()
    if args.voice:
        os.environ.pop("HF_HUB_OFFLINE", None)
        os.environ["HF_HOME"] = str(config.directory / "models/huggingface")
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "180"
        from pocket_tts import TTSModel
        print("Downloading personal voice model…", flush=True)
        TTSModel.load_model()
        print("Personal voice model ready. Add your own recording in Settings.", flush=True)
    else:
        from Backend.ModelSetup import download_models
        download_models(config, lambda message: print(message, flush=True))

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Setup failed: " + str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
