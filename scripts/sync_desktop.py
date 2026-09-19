"""Synchronize repository-owned desktop sources to a short Windows build path."""
import hashlib
import json
import os
import shutil
from pathlib import Path

root = Path(__file__).resolve().parent.parent
source = root / "desktop"
target = Path(os.environ["LOCALAPPDATA"]) / "Jarvis/build/frontend"
target.mkdir(parents=True, exist_ok=True)
manifest_path = target / "jarvis-source-manifest.json"
previous = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
current = {}
for directory in ("src", "public", "src-tauri"):
    for path in (source / directory).rglob("*"):
        if not path.is_file() or any(part in {"target", "gen", "node_modules"} for part in path.relative_to(source).parts):
            continue
        name = path.relative_to(source)
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        current[name.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
for name in ("index.html", "vite.config.ts", "tsconfig.json", "package.json", "package-lock.json"):
    shutil.copy2(source / name, target / name)
    current[name] = hashlib.sha256((source / name).read_bytes()).hexdigest()
# Only remove files that this synchronizer previously copied, and never outside its directory.
for name in previous.keys() - current.keys():
    path = (target / name).resolve()
    if not path.is_relative_to(target.resolve()) or path == target.resolve():
        raise RuntimeError("Refusing an unsafe stale-build path")
    if path.is_file():
        path.unlink()
config_path = target / "src-tauri/tauri.conf.json"
config = json.loads(config_path.read_text(encoding="utf-8"))
config["bundle"]["resources"] = {str(root / "dist/jarvis-engine") + "/": "engine/"}
config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
manifest_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
print(target)
