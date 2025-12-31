from __future__ import annotations
import argparse
import time
from collections import deque
from typing import Deque

import numpy as np

from .config import load_config
from .motion import MotionDetector
from .recorder import RecorderSettings, FFMpegRotatingRecorder
from .uploader import SFTPUploader, SFTPCfg
from .utils import ensure_dir, now_s

def _import_picamera2():
    try:
        from picamera2 import Picamera2
        return Picamera2
    except Exception as e:
        raise RuntimeError(
            "Picamera2 not available. On Raspberry Pi OS install: sudo apt install python3-picamera2"
        ) from e

def run(cfg_path: str) -> int:
    cfg = load_config(cfg_path)
    ensure_dir(cfg.recording.out_dir)

    Picamera2 = _import_picamera2()
    picam2 = Picamera2()

    video_config = picam2.create_video_configuration(
        main={"size": cfg.camera.main_size, "format": "RGB888"},
        lores={"size": cfg.camera.lores_size, "format": "RGB888"},
        controls={"FrameRate": cfg.camera.fps},
    )
    picam2.configure(video_config)
    picam2.start()

    detector = MotionDetector(
        method=cfg.motion.method,
        history=cfg.motion.mog2_history,
        var_threshold=cfg.motion.mog2_var_threshold,
        min_area=cfg.motion.min_area,
        blur_ksize=cfg.motion.blur_ksize,
        dilate_iter=cfg.motion.dilate_iter,
        erode_iter=cfg.motion.erode_iter,
    )

    rec_settings = RecorderSettings(
        out_dir=cfg.recording.out_dir,
        container=cfg.recording.container,
        fps=cfg.camera.fps,
        size=tuple(cfg.camera.main_size),
        bitrate=cfg.recording.bitrate,
        max_file_mb=cfg.recording.max_file_mb,
        encoder_preference=cfg.recording.encoder_preference,
        extra_ffmpeg_args=cfg.recording.extra_ffmpeg_args,
    )
    recorder = FFMpegRotatingRecorder(rec_settings)

    uploader = None
    if cfg.upload.enabled:
        upcfg = SFTPCfg(
            host=cfg.upload.host,
            port=cfg.upload.port,
            username=cfg.upload.username,
            password=cfg.upload.password,
            pkey_path=cfg.upload.pkey_path,
            remote_dir=cfg.upload.remote_dir,
            delete_after_upload=cfg.upload.delete_after_upload,
            max_retries=cfg.upload.max_retries,
            retry_backoff_seconds=cfg.upload.retry_backoff_seconds,
        )
        uploader = SFTPUploader(cfg.recording.out_dir, upcfg)
        uploader.start()
        print("[upload] watcher started")

    pre_frames = max(0, int(cfg.recording.prebuffer_seconds * cfg.camera.fps))
    ring: Deque[np.ndarray] = deque(maxlen=pre_frames)

    warmup_until = now_s() + cfg.motion.warmup_seconds
    recording = False
    record_start_t = 0.0
    last_motion_t = 0.0

    print("[start] motion recorder running")
    print(f"[cfg] out_dir={cfg.recording.out_dir} container={cfg.recording.container} max_file_mb={cfg.recording.max_file_mb}")

    try:
        while True:
            lo = picam2.capture_array("lores")  # RGB
            mr = detector.update(lo)

            t = now_s()
            motion_ok = (t >= warmup_until) and mr.motion

            if recording:
                main = picam2.capture_array("main")
                recorder.write_frame(main)

                if motion_ok:
                    last_motion_t = t

                if (t - last_motion_t) >= cfg.recording.stop_after_seconds:
                    dur = t - record_start_t
                    if dur >= cfg.recording.min_record_seconds:
                        final_path = recorder.stop()
                        recording = False
                        print(f"[rec] stop. duration={dur:.2f}s file={final_path}")
                    else:
                        last_motion_t = t
            else:
                if pre_frames > 0:
                    main_pre = picam2.capture_array("main")
                    ring.append(main_pre)

                if motion_ok:
                    recorder.start()
                    recording = True
                    record_start_t = t
                    last_motion_t = t
                    print(f"[rec] start. motion_score={mr.score:.1f}")

                    if pre_frames > 0 and len(ring) > 0:
                        for fr in list(ring):
                            recorder.write_frame(fr)
                        ring.clear()

            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\n[exit] Ctrl+C")
    finally:
        try:
            if recording:
                recorder.stop()
        except Exception:
            pass
        try:
            picam2.stop()
        except Exception:
            pass
        if uploader:
            uploader.stop()

    return 0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Path to YAML config")
    args = ap.parse_args()
    raise SystemExit(run(args.config))

if __name__ == "__main__":
    main()
