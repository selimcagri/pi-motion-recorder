#!/usr/bin/env bash
set -euo pipefail

sudo apt update
sudo apt install -y ffmpeg python3-opencv python3-picamera2 python3-pip
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

echo "Done."
