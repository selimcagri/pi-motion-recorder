# pi-motion-recorder

Raspberry Pi + Pi Camera motion-triggered recording:

- Detect motion with OpenCV
- Record only when motion exists (with optional pre-buffer)
- Rotate files by max size (default 128MB)
- Optional SFTP upload of finalized files (watcher-based)

## 1) Install (Raspberry Pi OS)

### APT deps
```bash
sudo apt update
sudo apt install -y ffmpeg python3-opencv python3-picamera2 python3-pip
```

### Python deps
```bash
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

> Note: On Pi, `python3-opencv` from apt is usually best (faster/compatible).
> `opencv-python` via pip may work but can be heavy.

## 2) Configure
Copy config:
```bash
cp config/config.example.yaml config/config.yaml
nano config/config.yaml
```

## 3) Run
```bash
python3 -m motionrec --config config/config.yaml
```

Logs will print to stdout.

## 4) Systemd service (optional)

Edit paths inside:
`scripts/systemd/motionrec.service`

Then:
```bash
sudo cp scripts/systemd/motionrec.service /etc/systemd/system/motionrec.service
sudo systemctl daemon-reload
sudo systemctl enable --now motionrec
sudo journalctl -u motionrec -f
```

## Output files
- Written as `.part` while recording
- Renamed to final extension when closed (e.g. `.mp4`)
- For each finalized video, a **sidecar CSV** is written with the same base name: `motion_... .csv`
- Watcher uploads only finalized files

## Encoding notes
Default uses `h264_v4l2m2m` if ffmpeg supports it, otherwise falls back to `libx264`.

Container default is `mp4` (recommended). You can set `container: mkv` or `avi` in config.
