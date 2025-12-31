from __future__ import annotations
import os
import time
from datetime import datetime

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def ts_name(prefix: str = "", ext: str = "") -> str:
    t = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    base = f"{prefix}{t}" if prefix else t
    return f"{base}{ext}"

def now_s() -> float:
    return time.monotonic()
