from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata
binaries, datas = [], []
datas.append(('scripts/voice_worker.py', 'scripts'))
for package in ('llama_cpp', 'ctranslate2', 'onnxruntime', 'av', '_sounddevice_data'):
    binaries += collect_dynamic_libs(package)
for package in ('faster_whisper', 'llama_cpp', '_sounddevice_data'):
    datas += collect_data_files(package)
for distribution in ('faster-whisper', 'ctranslate2', 'llama-cpp-python', 'huggingface-hub'):
    datas += copy_metadata(distribution)
a = Analysis(['Engine.py'], pathex=[], binaries=binaries, datas=datas,
    hiddenimports=['win32timezone', 'pythoncom', 'pywintypes', 'win32com.client',
        'comtypes', 'comtypes.gen.UIAutomationClient', '_cffi_backend', 'onnxruntime.capi._pybind_state'],
    hookspath=['scripts/hooks'], hooksconfig={}, runtime_hooks=[],
    excludes=['Frontend', 'PyQt5', 'PySide6', 'PySide2', 'torch', 'torchaudio', 'torchvision',
        'pocket_tts', 'tensorflow', 'jax', 'transformers', 'selenium', 'flask', 'groq', 'cohere',
        'gradio', 'IPython', 'notebook', 'matplotlib', 'pandas', 'pytest'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='jarvis-engine', debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='jarvis-engine')
