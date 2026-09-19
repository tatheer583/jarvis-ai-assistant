"""Read-only local setup diagnostic."""
from Backend.Config import Config
from Backend.Diagnostics import diagnose
import json

if __name__ == "__main__":
    print(json.dumps(diagnose(Config()), indent=2))
