"""Debug script to test Jarvis modules individually."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import dotenv_values
env = dotenv_values(".env")
print("=" * 60)
print("ENV CHECK")
print("=" * 60)
for k, v in env.items():
    if "KEY" in k or "KEY" in k.upper():
        print(f"  {k}: {'SET' if v else 'MISSING'}")
    else:
        print(f"  {k}: {v}")

print("\n" + "=" * 60)
print("TESTING: Backend.SpeechToText")
print("=" * 60)
try:
    import Backend.SpeechToText as stt
    print("  Module import: OK")
    print("  SetAssistantStatus callable:", callable(stt.SetAssistantStatus))
    print("  QueryModifier callable:", callable(stt.QueryModifier))
    print("  UniversalTranslator callable:", callable(stt.UniversalTranslator))
    # Test it writes Status.data without crashing
    stt.SetAssistantStatus("DebugTest...")
    import time; time.sleep(0.2)
    from pathlib import Path
    status_file = Path("Frontend/Files/Status.data")
    if status_file.exists():
        print(f"  Status.data written: '{status_file.read_text(encoding='utf-8').strip()}'")
    stt.SetAssistantStatus("Available...")
except Exception as e:
    import traceback; traceback.print_exc()

print("\n" + "=" * 60)
print("TESTING: Backend.TextToSpeech")
print("=" * 60)
try:
    import Backend.TextToSpeech as tts
    print("  Module import: OK")
    print("  SetAssistantStatus callable:", callable(tts.SetAssistantStatus))
    print("  is_speaking callable:", callable(tts.is_speaking))
    print("  stop_speaking callable:", callable(tts.stop_speaking))
    # Test it writes Status.data
    tts.SetAssistantStatus("DebugTest...")
    import time; time.sleep(0.2)
    from pathlib import Path
    status_file = Path("Frontend/Files/Status.data")
    if status_file.exists():
        print(f"  Status.data written: '{status_file.read_text(encoding='utf-8').strip()}'")
    tts.SetAssistantStatus("Available...")
except Exception as e:
    import traceback; traceback.print_exc()

print("\n" + "=" * 60)
print("TESTING: Backend.ImageGenration")
print("=" * 60)
try:
    import Backend.ImageGenration as img
    print("  Module import: OK")
    print("  HuggingFaceAPIKey:", 'SET' if img.HuggingFaceAPIKey else 'MISSING')
    print("  API_URL:", img.API_URL)
    print("  SIGNAL_PATH:", img.SIGNAL_PATH)
    print("  SIGNAL_PATH_ALT:", img.SIGNAL_PATH_ALT)
    print("  headers configured:", bool(img.headers.get("Authorization")))
except Exception as e:
    import traceback; traceback.print_exc()

print("\n" + "=" * 60)
print("TESTING: Groq Whisper STT connectivity")
print("=" * 60)
try:
    from groq import Groq
    client = Groq(api_key=env.get("GroqAPIKey", ""))
    models = client.models.list()
    whisper_model = next((m for m in models.data if "whisper" in m.id), None)
    if whisper_model:
        print(f"  Whisper model available: {whisper_model.id}")
    else:
        print("  WARNING: No whisper model found in account")
        print("  Available models:", [m.id for m in models.data[:10]])
except Exception as e:
    import traceback; traceback.print_exc()

print("\n" + "=" * 60)
print("TESTING: HuggingFace API connectivity")
print("=" * 60)
try:
    import requests
    hf_key = env.get("HuggingFaceAPIKey", "")
    headers = {"Authorization": f"Bearer {hf_key}"}
    resp = requests.get(
        "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0",
        headers=headers, timeout=30
    )
    print(f"  HF API status: {resp.status_code}")
    if resp.ok:
        data = resp.json()
        if isinstance(data, list) and len(data) > 0:
            model_state = data[0].get("model", {}).get("state", "unknown")
            print(f"  Model state: {model_state}")
            if model_state == "LOADING":
                print("  WARNING: Model is still loading on HF inference endpoint")
                print("  Expected time:", data[0].get("model", {}).get("estimated_time"))
        else:
            print("  Response:", str(data)[:200])
    else:
        print(f"  Error: {resp.text[:300]}")
except Exception as e:
    import traceback; traceback.print_exc()

print("\n" + "=" * 60)
print("TESTING: Cohere API")
print("=" * 60)
try:
    import requests as req
    cohere_key = env.get("CohereAPIKey", "")
    resp = req.post(
        "https://api.cohere.ai/v1/chat",
        headers={"Authorization": f"Bearer {cohere_key}", "Content-Type": "application/json"},
        json={"model": "command-r-08-2024", "message": "test", "max_tokens": 5},
        timeout=30
    )
    print(f"  Cohere API status: {resp.status_code}")
    if resp.ok:
        print("  Cohere API: OK")
    else:
        print(f"  Error: {resp.text[:300]}")
except Exception as e:
    import traceback; traceback.print_exc()

print("\n" + "=" * 60)
print("TESTING: Frontend.GUI module")
print("=" * 60)
try:
    import Frontend.GUI as gui
    print("  Module import: OK")
    print("  SetAssistantStatus callable:", callable(gui.SetAssistantStatus))
    print("  GetAssistantStatus callable:", callable(gui.GetAssistantStatus))
    print("  SetMicrophoneStatus callable:", callable(gui.SetMicrophoneStatus))
    print("  GetMicrophoneStatus callable:", callable(gui.GetMicrophoneStatus))
    gui.SetAssistantStatus("DebugTest...")
    import time; time.sleep(0.2)
    from pathlib import Path
    status_file = Path("Frontend/Files/Status.data")
    if status_file.exists():
        print(f"  Status.data written: '{status_file.read_text(encoding='utf-8').strip()}'")
    gui.SetAssistantStatus("Available...")
except Exception as e:
    import traceback; traceback.print_exc()

print("\n" + "=" * 60)
print("ALL TESTS DONE")
print("=" * 60)
