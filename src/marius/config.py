import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

CONFIG_DIR = Path.home() / ".config" / "marius"
CONFIG_PATH = CONFIG_DIR / "config.json"

class Config:
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        self.data = self.load()

    def load(self) -> Dict[str, Any]:
        if self.path.exists():
            try:
                with open(self.path, "r") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any):
        self.data[key] = value
        self.save()

def get_config() -> Config:
    return Config(CONFIG_PATH)
