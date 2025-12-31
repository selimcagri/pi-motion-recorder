from __future__ import annotations
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional, List
import numpy as np

from .utils import ensure_dir, ts_name

@dataclass
class RecorderSettings:
    out_dir: str
    container: str
    fps: int
    size: tuple[int, int]
    bitrate: str
    max_file_mb: int
    encoder_preference: List[str]
    extra_ffmpeg_args: List[str]

class FFMpegRotatingRecorder:
    """
    Writes raw RGB frames into ffmpeg stdin. Rotates output file when size exceeds limit.
    Uses .part while writing, then renames to final extension on close.
    """
    def __init__(self, settings: RecorderSettings):
        self.s = settings
        ensure_dir(self.s.out_dir)

        self._lock = threading.RLock()
        self._proc: Optional[subprocess.Popen] = None
        self._current_part: Optional[str] = None
        self._current_final: Optional[str] = None
        self._running = False
        self._rotate_flag = False
        self._monitor_thread: Optional[threading.Thread] = None

    def _build_cmd(self, encoder: str, out_part: str) -> list[str]:
        w, h = self.s.size
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-y",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{w}x{h}",
            "-r", str(self.s.fps),
            "-i", "pipe:0",
            "-an",
            "-c:v", encoder,
            "-b:v", self.s.bitrate,
        ]
        cmd += self.s.extra_ffmpeg_args
        cmd += [out_part]
        return cmd

    def _start_proc(self) -> None:
        assert self._current_part is not None
        last_err = None

        for enc in self.s.encoder_preference:
            cmd = self._build_cmd(enc, self._current_part)
            try:
                p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
                time.sleep(0.2)
                if p.poll() is not None:
                    err = (p.stderr.read() if p.stderr else b"").decode("utf-8", "ignore")
                    last_err = f"ffmpeg failed with encoder={enc}: {err.strip()}"
                    continue
                self._proc = p
                return
            except Exception as e:
                last_err = f"ffmpeg spawn error encoder={enc}: {e!r}"

        raise RuntimeError(last_err or "Could not start ffmpeg with any encoder")

    def start_new_file(self) -> None:
        with self._lock:
            ext = "." + self.s.container.lower().lstrip(".")
            base = ts_name(prefix="motion_", ext=ext)
            final_path = os.path.join(self.s.out_dir, base)
            part_path = final_path + ".part"

            self._current_final = final_path
            self._current_part = part_path

            self._start_proc()

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self.start_new_file()
            self._monitor_thread = threading.Thread(target=self._monitor_size_loop, daemon=True)
            self._monitor_thread.start()

    def _monitor_size_loop(self) -> None:
        limit = self.s.max_file_mb * 1024 * 1024
        margin = 1 * 1024 * 1024  # 1MB safety
        while True:
            with self._lock:
                if not self._running:
                    return
                part = self._current_part
            if part and os.path.exists(part):
                try:
                    sz = os.path.getsize(part)
                    if sz >= max(1, limit - margin):
                        with self._lock:
                            self._rotate_flag = True
                except OSError:
                    pass
            time.sleep(0.5)

    def write_frame(self, frame_rgb: np.ndarray) -> None:
        with self._lock:
            if not self._running or self._proc is None or self._proc.stdin is None:
                return

            if self._rotate_flag:
                self._rotate_flag = False
                self._rotate()

            try:
                self._proc.stdin.write(frame_rgb.tobytes())
            except BrokenPipeError:
                self._restart_ffmpeg()

    def _restart_ffmpeg(self) -> None:
        self._close_current_proc(finalize=False)
        self._start_proc()

    def _close_current_proc(self, finalize: bool = True) -> None:
        if self._proc:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None

        if finalize and self._current_part and self._current_final:
            try:
                if os.path.exists(self._current_part):
                    os.replace(self._current_part, self._current_final)
            except Exception:
                pass

    def _rotate(self) -> None:
        self._close_current_proc(finalize=True)
        self.start_new_file()

    def stop(self) -> Optional[str]:
        with self._lock:
            if not self._running:
                return None
            self._running = False
            self._close_current_proc(finalize=True)
            return self._current_final
