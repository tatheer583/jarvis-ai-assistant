"""Explicit, one-time public model downloads. Never called during inference."""
from __future__ import annotations
import os
import shutil
from pathlib import Path
from Backend.Config import Config

SPEECH_REPO = "Systran/faster-whisper-base"
CHAT_REPO = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
CHAT_FILE = "qwen2.5-1.5b-instruct-q4_k_m.gguf"

def download_models(config: Config, progress=print):
    # Imports happen only in the explicit setup subprocess, never in the assistant.
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "180"
    os.environ["HF_HUB_ETAG_TIMEOUT"] = "60"
    from huggingface_hub import hf_hub_download, snapshot_download
    models = config.directory / "models"
    models.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(models).free < 2 * 1024 ** 3:
        raise RuntimeError("Free at least 2 GB for the local speech and chat models.")
    progress("Downloading multilingual speech model (about 150 MB)…")
    speech = models / "whisper-base"
    snapshot_download(SPEECH_REPO, local_dir=speech, token=False,
                      allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.*", "preprocessor_config.json"],
                      max_workers=2)
    if not (speech / "model.bin").is_file() or not (speech / "tokenizer.json").is_file():
        raise RuntimeError("The speech download is incomplete. Run setup again to resume.")
    progress("Downloading local chat model (about 1.1 GB)…")
    chat = hf_hub_download(CHAT_REPO, CHAT_FILE, local_dir=models, token=False)
    if Path(chat).stat().st_size < 1024 * 1024:
        raise RuntimeError("The chat download is incomplete.")
    config.update({"whisper_path": str(speech), "llm_path": str(chat)})
    progress("Local speech and chat models are ready. No API keys are needed.")
