#!/usr/bin/env python3
"""AQL Vision camera agent for Raspberry Pi.

Captures JPEG frames and publishes the current frame through the AQL Vision
device endpoint. Secrets are read from environment variables and are never
stored in this file.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import requests


SUPABASE_URL = os.getenv("AQL_SUPABASE_URL", "https://djeijlkqypvaznmlvtxe.supabase.co").rstrip("/")
UPLOAD_URL = os.getenv("AQL_CAPTURE_UPLOAD_URL", f"{SUPABASE_URL}/functions/v1/vision-captures/live")
HEARTBEAT_URL = os.getenv("AQL_HEARTBEAT_URL", f"{SUPABASE_URL}/functions/v1/vision-device-heartbeat")
DEVICE_TOKEN = os.getenv("AQL_DEVICE_TOKEN", "").strip()

KIT_ID = os.getenv("AQL_KIT_ID", "92ee721d-f3c0-4a76-8e28-a859d0c17f34")
CAMERA_ID = os.getenv("AQL_CAMERA_ID", "af8b2fef-c2b0-49d5-8460-b06d73a88853")
CAMERA_CODE = os.getenv("AQL_CAMERA_CODE", "tanque01")
LIVE_FEED_PATH = os.getenv("AQL_LIVE_FEED_PATH", "live/tanque01/feed.jpg")

WIDTH = int(os.getenv("AQL_CAMERA_WIDTH", "1920"))
HEIGHT = int(os.getenv("AQL_CAMERA_HEIGHT", "1080"))
FRAME_INTERVAL_MS = max(1, int(os.getenv("AQL_FRAME_INTERVAL_MS", "2000")))
JPEG_QUALITY = min(95, max(30, int(os.getenv("AQL_JPEG_QUALITY", "70"))))
REQUEST_TIMEOUT_SECONDS = max(5, int(os.getenv("AQL_REQUEST_TIMEOUT_SECONDS", "30")))
HEARTBEAT_INTERVAL_SECONDS = max(15, int(os.getenv("AQL_HEARTBEAT_INTERVAL_SECONDS", "120")))
OFFLINE_DIR = Path(os.getenv("AQL_OFFLINE_DIR", "/var/lib/aql-vision/offline"))
OFFLINE_BUFFER_HOURS = max(1, int(os.getenv("AQL_OFFLINE_BUFFER_HOURS", "72")))


class Camera(Protocol):
    def capture(self) -> bytes: ...
    def close(self) -> None: ...


class Picamera2Camera:
    def __init__(self) -> None:
        from picamera2 import Picamera2

        self._camera = Picamera2()
        config = self._camera.create_still_configuration(main={"size": (WIDTH, HEIGHT), "format": "RGB888"})
        self._camera.configure(config)
        self._camera.start()
        time.sleep(1.5)

    def capture(self) -> bytes:
        import cv2

        frame = self._camera.capture_array("main")
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            raise RuntimeError("Could not encode the camera frame as JPEG")
        return encoded.tobytes()

    def close(self) -> None:
        self._camera.stop()
        self._camera.close()


class OpenCVCamera:
    def __init__(self) -> None:
        import cv2

        device = int(os.getenv("AQL_CAMERA_DEVICE", "0"))
        self._cv2 = cv2
        self._camera = cv2.VideoCapture(device)
        self._camera.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        self._camera.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        if not self._camera.isOpened():
            raise RuntimeError(f"Could not open camera device {device}")

    def capture(self) -> bytes:
        ok, frame = self._camera.read()
        if not ok:
            raise RuntimeError("Could not read a camera frame")
        ok, encoded = self._cv2.imencode(".jpg", frame, [self._cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            raise RuntimeError("Could not encode the camera frame as JPEG")
        return encoded.tobytes()

    def close(self) -> None:
        self._camera.release()


def open_camera() -> Camera:
    try:
        camera = Picamera2Camera()
        print("Camera backend: Picamera2", flush=True)
        return camera
    except (ImportError, ModuleNotFoundError):
        camera = OpenCVCamera()
        print("Camera backend: OpenCV", flush=True)
        return camera


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def upload_frame(session: requests.Session, jpeg: bytes, captured_at: str) -> None:
    metadata = {
        "kit_id": KIT_ID,
        "camera_id": CAMERA_ID,
        "camera_code": CAMERA_CODE,
        "live_feed_path": LIVE_FEED_PATH,
        "captured_at": captured_at,
        "resolution": f"{WIDTH}x{HEIGHT}",
    }
    response = session.post(
        UPLOAD_URL,
        headers={"X-AQL-Device-Token": DEVICE_TOKEN},
        data={
            "kit_id": KIT_ID,
            "camera_id": CAMERA_ID,
            "camera_code": CAMERA_CODE,
            "live_feed_path": LIVE_FEED_PATH,
            "captured_at": captured_at,
            "metadata": json.dumps(metadata, separators=(",", ":")),
        },
        files={"image": ("feed.jpg", jpeg, "image/jpeg")},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if not response.ok:
        detail = response.text[:500].strip()
        raise RuntimeError(f"Upload failed ({response.status_code}): {detail}")


def send_heartbeat(session: requests.Session, camera_ok: bool) -> int:
    response = session.post(
        HEARTBEAT_URL,
        headers={"X-AQL-Device-Token": DEVICE_TOKEN},
        json={
            "kit_id": KIT_ID,
            "camera_ids": [CAMERA_ID],
            "camera_codes": [CAMERA_CODE],
            "sensor_ids": [],
            "status": "online",
            "camera_ok": camera_ok,
            "sensors_ok": True,
            "timestamp": utc_now(),
            "metadata": {"agent": "aql-vision-raspberry", "version": "1.1"},
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if not response.ok:
        raise RuntimeError(f"Heartbeat failed ({response.status_code}): {response.text[:500].strip()}")
    payload = response.json()
    return max(15, int(payload.get("next_heartbeat_seconds", HEARTBEAT_INTERVAL_SECONDS)))


def store_offline(jpeg: bytes, captured_at: str) -> None:
    OFFLINE_DIR.mkdir(parents=True, exist_ok=True)
    safe_time = captured_at.replace(":", "-")
    (OFFLINE_DIR / f"{safe_time}.jpg").write_bytes(jpeg)


def clean_offline_buffer() -> None:
    if not OFFLINE_DIR.exists():
        return
    cutoff = time.time() - OFFLINE_BUFFER_HOURS * 3600
    for image in OFFLINE_DIR.glob("*.jpg"):
        try:
            if image.stat().st_mtime < cutoff:
                image.unlink()
        except OSError:
            pass


def validate_configuration() -> None:
    if not DEVICE_TOKEN:
        raise SystemExit("AQL_DEVICE_TOKEN is missing. Export it before starting the agent.")
    if not KIT_ID or not CAMERA_ID or not CAMERA_CODE:
        raise SystemExit("Kit and camera identifiers must not be empty.")


def main() -> int:
    validate_configuration()
    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    session = requests.Session()
    camera = open_camera()
    next_capture = time.monotonic()
    next_heartbeat = 0.0
    failures = 0
    print(f"AQL Vision agent started: {CAMERA_CODE} -> {LIVE_FEED_PATH}", flush=True)

    try:
        while running:
            if time.monotonic() >= next_heartbeat:
                try:
                    heartbeat_interval = send_heartbeat(session, failures == 0)
                    next_heartbeat = time.monotonic() + heartbeat_interval
                    print(f"{utc_now()} heartbeat OK; next in {heartbeat_interval}s", flush=True)
                except Exception as error:
                    next_heartbeat = time.monotonic() + 15
                    print(f"{utc_now()} heartbeat error: {error}", file=sys.stderr, flush=True)
            wait = next_capture - time.monotonic()
            if wait > 0:
                time.sleep(min(wait, 0.25))
                continue
            next_capture = time.monotonic() + FRAME_INTERVAL_MS / 1000
            captured_at = utc_now()
            try:
                jpeg = camera.capture()
                upload_frame(session, jpeg, captured_at)
                failures = 0
                print(f"{captured_at} frame published ({len(jpeg)} bytes)", flush=True)
            except Exception as error:
                failures += 1
                if "jpeg" in locals():
                    try:
                        store_offline(jpeg, captured_at)
                    except OSError:
                        pass
                clean_offline_buffer()
                print(f"{captured_at} publish error #{failures}: {error}", file=sys.stderr, flush=True)
                time.sleep(min(30, 2 ** min(failures, 5)))
    finally:
        camera.close()
        session.close()
        print("AQL Vision agent stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
