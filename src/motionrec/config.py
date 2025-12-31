from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple, Optional, Any, Dict
import yaml

@dataclass
class CameraCfg:
    main_size: Tuple[int, int]
    lores_size: Tuple[int, int]
    fps: int

@dataclass
class MotionCfg:
    method: str
    mog2_history: int
    mog2_var_threshold: int
    min_area: int
    blur_ksize: int
    dilate_iter: int
    erode_iter: int
    warmup_seconds: float

@dataclass
class RecordingCfg:
    out_dir: str
    container: str
    max_file_mb: int
    prebuffer_seconds: float
    stop_after_seconds: float
    min_record_seconds: float
    bitrate: str
    encoder_preference: List[str]
    extra_ffmpeg_args: List[str]

@dataclass
class UploadCfg:
    enabled: bool
    host: str
    port: int
    username: str
    password: Optional[str]
    pkey_path: Optional[str]
    remote_dir: str
    delete_after_upload: bool
    max_retries: int
    retry_backoff_seconds: int

@dataclass
class AppCfg:
    camera: CameraCfg
    motion: MotionCfg
    recording: RecordingCfg
    upload: UploadCfg

def _get(d: Dict[str, Any], k: str, default: Any = None) -> Any:
    return d.get(k, default)

def load_config(path: str) -> AppCfg:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    cam = raw["camera"]
    mot = raw["motion"]
    rec = raw["recording"]
    up  = raw.get("upload", {})

    camera = CameraCfg(
        main_size=tuple(cam["main_size"]),
        lores_size=tuple(cam["lores_size"]),
        fps=int(cam["fps"]),
    )
    motion = MotionCfg(
        method=str(mot.get("method", "mog2")),
        mog2_history=int(mot.get("mog2_history", 300)),
        mog2_var_threshold=int(mot.get("mog2_var_threshold", 24)),
        min_area=int(mot.get("min_area", 1200)),
        blur_ksize=int(mot.get("blur_ksize", 7)),
        dilate_iter=int(mot.get("dilate_iter", 2)),
        erode_iter=int(mot.get("erode_iter", 1)),
        warmup_seconds=float(mot.get("warmup_seconds", 2.0)),
    )
    recording = RecordingCfg(
        out_dir=str(rec.get("out_dir", "./recordings")),
        container=str(rec.get("container", "mp4")).lower(),
        max_file_mb=int(rec.get("max_file_mb", 128)),
        prebuffer_seconds=float(rec.get("prebuffer_seconds", 2.0)),
        stop_after_seconds=float(rec.get("stop_after_seconds", 3.0)),
        min_record_seconds=float(rec.get("min_record_seconds", 2.0)),
        bitrate=str(rec.get("bitrate", "3M")),
        encoder_preference=list(rec.get("encoder_preference", ["h264_v4l2m2m", "libx264"])),
        extra_ffmpeg_args=list(rec.get("extra_ffmpeg_args", ["-movflags", "+faststart"])),
    )
    upload = UploadCfg(
        enabled=bool(up.get("enabled", False)),
        host=str(up.get("host", "")),
        port=int(up.get("port", 22)),
        username=str(up.get("username", "")),
        password=_get(up, "password", None),
        pkey_path=_get(up, "pkey_path", None),
        remote_dir=str(up.get("remote_dir", "")),
        delete_after_upload=bool(up.get("delete_after_upload", False)),
        max_retries=int(up.get("max_retries", 5)),
        retry_backoff_seconds=int(up.get("retry_backoff_seconds", 10)),
    )

    return AppCfg(camera=camera, motion=motion, recording=recording, upload=upload)
