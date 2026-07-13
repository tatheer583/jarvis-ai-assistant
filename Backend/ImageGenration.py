import asyncio
import json
from pathlib import Path
from random import randint
from time import sleep

import requests
from PIL import Image
from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
DATA_DIR = BASE_DIR / "Data"
SIGNAL_PATH = BASE_DIR / "Frontend" / "Files" / "ImageGeneration.data"
SIGNAL_PATH_ALT = None  # Kept for backward compat only; driver uses IMAGE_SIGNAL_PATHS from Main.py
DATA_DIR.mkdir(parents=True, exist_ok=True)
SIGNAL_PATH.parent.mkdir(parents=True, exist_ok=True)

env_vars = dotenv_values(str(ENV_PATH))
HuggingFaceAPIKey = env_vars.get("HuggingFaceAPIKey", "")

API_URL = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
headers = {"Authorization": f"Bearer {HuggingFaceAPIKey}"}


def open_images(prompt: str) -> None:
    prompt_folder = prompt.replace(" ", "_")
    files = [f"{prompt_folder}{i}.jpg" for i in range(1, 5)]

    for jpg_file in files:
        image_path = DATA_DIR / jpg_file

        try:
            img = Image.open(image_path)
            print(f"Opening image: {image_path}")
            img.show()
            sleep(1)
        except IOError:
            print(f"Unable to open {image_path}")


def _reset_signal_files() -> None:
    SIGNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        SIGNAL_PATH.write_text("False,False", encoding="utf-8")
    except Exception as error:
        print(f"Failed to reset signal file {SIGNAL_PATH}: {error}")


def _extract_error(response: requests.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return str(payload.get("error") or payload.get("message") or payload)
        return json.dumps(payload)
    except Exception:
        return response.text[:300].strip() or f"HTTP {response.status_code}"


async def query(payload: dict[str, str]) -> requests.Response:
    return await asyncio.to_thread(
        requests.post,
        API_URL,
        headers=headers,
        json=payload,
        timeout=120,
    )


def _save_image_response(response: requests.Response, prompt: str, index: int) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    if not response.ok:
        raise RuntimeError(_extract_error(response))
    if not content_type.startswith("image/"):
        raise RuntimeError(_extract_error(response))

    content = response.content
    if len(content) < 2048:
        raise RuntimeError(f"Response too small ({len(content)} bytes) to be a valid image. Likely an error: {response.text[:300].strip()}")

    out_path = DATA_DIR / f"{prompt.replace(' ', '_')}{index}.jpg"
    out_path.write_bytes(content)
    return True


async def generate_images(prompt: str) -> int:
    if not HuggingFaceAPIKey:
        raise RuntimeError("HuggingFaceAPIKey is missing.")

    tasks = []

    for _ in range(4):
        payload = {
            "input": f"{prompt}, quality=4k, sharpness=maximum/ Ultra High details, high resolution, seed = {randint(0, 1000000)}",
        }
        task = asyncio.create_task(query(payload))
        tasks.append(task)

    responses = await asyncio.gather(*tasks)
    saved = 0

    for i, response in enumerate(responses, start=1):
        try:
            if _save_image_response(response, prompt, i):
                saved += 1
        except Exception as error:
            print(f"Image {i} failed: {error}")

    return saved


def GenerateImages(prompt: str) -> bool:
    saved = asyncio.run(generate_images(prompt))
    if saved <= 0:
        raise RuntimeError("Image generation failed for all requested outputs.")
    open_images(prompt)
    return True


def wait_for_signal() -> None:
    while True:
        try:
            if not SIGNAL_PATH.exists():
                _reset_signal_files()
                sleep(1)
                continue

            data = SIGNAL_PATH.read_text(encoding="utf-8").strip()
            if not data or "," not in data:
                _reset_signal_files()
                sleep(1)
                continue

            prompt, status = data.split(",", maxsplit=1)

            if status.strip() == "True":
                print(f"GenerateImages triggered: {prompt}")
                try:
                    GenerateImages(prompt=prompt.strip())
                finally:
                    _reset_signal_files()
                break
            sleep(1)
        except Exception as e:
            print(f"ImageGenration waiting: {e}")
            sleep(1)


if __name__ == "__main__":
    wait_for_signal()