"""No cloud image generation. A local image model is not bundled with this edition."""

def GenerateImages(prompt: str) -> bool:
    raise RuntimeError("Local image generation requires a separately installed image model. No cloud requests are made.")

ImageGenerator = GenerateImages

if __name__ == "__main__":
    print("Use Jarvis Desktop. Local image generation is not installed.")
