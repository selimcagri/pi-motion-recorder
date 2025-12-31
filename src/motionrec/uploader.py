from __future__ import annotations
import os
import queue
import time
import threading
from dataclasses import dataclass
from typing import Optional

import paramiko
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

@dataclass
class SFTPCfg:
    host: str
    port: int
    username: str
    password: Optional[str]
    pkey_path: Optional[str]
    remote_dir: str
    delete_after_upload: bool
    max_retries: int
    retry_backoff_seconds: int

class _Handler(FileSystemEventHandler):
    def __init__(self, q: queue.Queue[str]):
        self.q = q

    def on_created(self, event):
        if event.is_directory:
            return
        path = event.src_path
        if path.endswith(".part"):
            return
        self.q.put(path)

    def on_moved(self, event):
        if event.is_directory:
            return
        dest = getattr(event, "dest_path", None)
        if not dest or dest.endswith(".part"):
            return
        self.q.put(dest)

class SFTPUploader:
    def __init__(self, local_dir: str, cfg: SFTPCfg):
        self.local_dir = local_dir
        self.cfg = cfg
        self.q: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

        self._observer = Observer()
        self._observer.schedule(_Handler(self.q), path=self.local_dir, recursive=False)

    def start(self) -> None:
        self._observer.start()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._observer.stop()
            self._observer.join(timeout=2)
        except Exception:
            pass

    def _connect(self) -> paramiko.SFTPClient:
        transport = paramiko.Transport((self.cfg.host, self.cfg.port))
        if self.cfg.pkey_path:
            key = paramiko.Ed25519Key.from_private_key_file(self.cfg.pkey_path)
            transport.connect(username=self.cfg.username, pkey=key)
        else:
            transport.connect(username=self.cfg.username, password=self.cfg.password)
        return paramiko.SFTPClient.from_transport(transport)

    def _ensure_remote_dir(self, sftp: paramiko.SFTPClient, path: str) -> None:
        parts = [p for p in path.split("/") if p]
        cur = ""
        for p in parts:
            cur += "/" + p
            try:
                sftp.stat(cur)
            except IOError:
                try:
                    sftp.mkdir(cur)
                except Exception:
                    pass

    def _upload_one(self, path: str) -> bool:
        if not os.path.exists(path) or os.path.isdir(path):
            return True

        # wait for file to become stable (not being written)
        try:
            sz1 = os.path.getsize(path)
            time.sleep(0.5)
            sz2 = os.path.getsize(path)
            if sz1 != sz2:
                return False
        except OSError:
            return False

        sftp = self._connect()
        try:
            self._ensure_remote_dir(sftp, self.cfg.remote_dir)
            remote_path = self.cfg.remote_dir.rstrip("/") + "/" + os.path.basename(path)
            sftp.put(path, remote_path)
        finally:
            try:
                sftp.close()
            except Exception:
                pass

        if self.cfg.delete_after_upload:
            try:
                os.remove(path)
            except Exception:
                pass
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                path = self.q.get(timeout=0.5)
            except queue.Empty:
                continue

            for _i in range(self.cfg.max_retries):
                if self._stop.is_set():
                    break
                try:
                    ok = self._upload_one(path)
                    if ok:
                        break
                except Exception:
                    pass
                time.sleep(self.cfg.retry_backoff_seconds)

            self.q.task_done()
