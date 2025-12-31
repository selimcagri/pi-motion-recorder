from __future__ import annotations
import os
import subprocess
import threading
import time
import csv
from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime

import numpy as np

from .utils import ensure_dir, ts_name, now_s

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

    Behavior:
    - Writes to `<final>.<ext>.part` while recording
    - On segment finalize (rotation or stop), renames `.part` -> final file
    - Creates a sidecar CSV with the same base name as the video:
        `<final_without_ext>.csv`
      containing one row with clip metadata.
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

        # Segment metadata
        self._segment_start_wall: Optional[datetime] = None
        self._segment_start_mono: float = 0.0
        self._frames_in_segment: int = 0
        self._encoder_used: str = ""

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
                self._encoder_used = enc
                return
            except Exception as e:
                last_err = f"ffmpeg spawn error encoder={enc}: {e!r}"

        raise RuntimeError(last_err or "Could not start ffmpeg with any encoder")

    def _segment_init(self) -> None:
        self._segment_start_wall = datetime.now()
        self._segment_start_mono = now_s()
        self._frames_in_segment = 0

    def start_new_file(self) -> None:
        with self._lock:
            ext = "." + self.s.container.lower().lstrip(".")
            base = ts_name(prefix="motion_", ext=ext)
            final_path = os.path.join(self.s.out_dir, base)
            part_path = final_path + ".part"

            self._current_final = final_path
            self._current_part = part_path

            self._segment_init()
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
                self._frames_in_segment += 1
            except BrokenPipeError:
                self._restart_ffmpeg()

    def _restart_ffmpeg(self) -> None:
        # Try to continue writing to the same part file (don't finalize).
        self._close_current_proc(finalize=False)
        self._start_proc()

    def _csv_path_for_video(self, final_video_path: str) -> str:
        base, _ext = os.path.splitext(final_video_path)
        return base + ".csv"

    def _write_sidecar_csv(self, final_video_path: str, start_wall: datetime, end_wall: datetime,
                           duration_s: float, frames: int) -> None:
        csv_path = self._csv_path_for_video(final_video_path)
        w, h = self.s.size
        row = {
            "video_file": os.path.basename(final_video_path),
            "start_time_local": start_wall.isoformat(timespec="seconds"),
            "end_time_local": end_wall.isoformat(timespec="seconds"),
            "duration_s": f"{duration_s:.3f}",
            "fps": str(self.s.fps),
            "frames": str(frames),
            "encoder": self._encoder_used,
            "bitrate": self.s.bitrate,
            "width": str(w),
            "height": str(h),
            "container": self.s.container,
        }
        try:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(row.keys()))
                writer.writeheader()
                writer.writerow(row)
        except Exception:
            pass

    def _close_current_proc(self, finalize: bool = True) -> None:
        # Snapshot metadata for this segment
        final_path = self._current_final
        part_path = self._current_part
        start_wall = self._segment_start_wall or datetime.now()
        start_mono = self._segment_start_mono
        frames = self._frames_in_segment

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

        if finalize and part_path and final_path:
            try:
                if os.path.exists(part_path):
                    os.replace(part_path, final_path)
            except Exception:
                return

            # Sidecar CSV for this finalized file
            try:
                end_wall = datetime.now()
                duration_s = max(0.0, now_s() - start_mono)
                self._write_sidecar_csv(final_path, start_wall, end_wall, duration_s, frames)
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
