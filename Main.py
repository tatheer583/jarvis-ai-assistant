"""Jarvis Local Desktop: native UI, local models, no cloud API connections."""
from __future__ import annotations
import argparse
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

def configure_runtime():
    # Downloading is an explicit setup command in a separate process.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    from Backend.Config import Config
    config = Config()
    handler = RotatingFileHandler(config.directory / "jarvis.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s", handlers=[handler])
    return config

def main():
    parser = argparse.ArgumentParser(description="Jarvis local desktop assistant")
    parser.add_argument("--engine", action="store_true", help="Run the local Tauri engine over standard input/output")
    parser.add_argument("--download-models", action="store_true", help="Explicit one-time model download")
    parser.add_argument("--no-listen", action="store_true")
    parser.add_argument("--check", action="store_true", help="Report local setup without opening the GUI or microphone")
    parser.add_argument("--command", help="Execute one desktop command and print its result")
    args = parser.parse_args()
    config = configure_runtime()
    if args.download_models:
        from Backend.ModelSetup import download_models
        download_models(config, lambda text: print(text, flush=True))
        return 0
    if args.engine:
        from Backend.EngineService import serve
        return serve(config, no_listen=args.no_listen)
    if args.check:
        from Backend.Diagnostics import diagnose
        print(json.dumps(diagnose(config), ensure_ascii=False, indent=2))
        return 0
    if args.command:
        from Backend.Services import Services
        result = Services(config).execute(args.command, source="cli")
        print(result.message)
        return 0 if result.success else 1
    from Frontend.GUI import GraphicalUserInterface
    return GraphicalUserInterface()

if __name__ == "__main__":
    sys.exit(main())
