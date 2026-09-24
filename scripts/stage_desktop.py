"""Create a new staged app without overwriting the existing working release."""
import datetime
import hashlib
import json
import os
import shutil
from pathlib import Path

root = Path(__file__).resolve().parent.parent
build = Path(os.environ["LOCALAPPDATA"]) / "Jarvis/build"
stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
output = root / "artifacts/staging" / ("Jarvis-" + stamp)
output.mkdir(parents=True, exist_ok=False)
shutil.copy2(build / "target/release/jarvis-desktop.exe", output / "jarvis-desktop.exe")
shutil.copytree(root / "dist/jarvis-engine", output / "engine")
manifest = json.loads((build / "frontend/jarvis-source-manifest.json").read_text())
sources = [root / "Main.py", root / "Engine.py", root / "jarvis-engine.spec"]
sources += list((root / "Backend").rglob("*.py"))
for path in sources:
    manifest[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
executables = {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
               for name in ("jarvis-desktop.exe", "engine/jarvis-engine.exe")}
(output / "build-manifest.json").write_text(json.dumps({
    "created": stamp, "source_sha256": manifest, "executable_sha256": executables,
    "validation": "Built only. Run the packaged smoke test before promotion."
}, indent=2), encoding="utf-8")
print(output)
