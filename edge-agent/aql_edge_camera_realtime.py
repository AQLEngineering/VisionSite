import asyncio
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import ssl
import stat
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:
    import cv2
except ImportError as exc:
    raise RuntimeError(
        "OpenCV nao esta instalado. Corre: pip install -r edge-device/requirements.txt"
    ) from exc

try:
    from picamera2 import Picamera2
except ImportError:
    Picamera2 = None

try:
    import httpx
except ImportError as exc:
    raise RuntimeError(
        "httpx nao esta instalado. Corre: pip install -r edge-device/requirements.txt"
    ) from exc

try:
    from supabase import AsyncClient, acreate_client
except ImportError as exc:
    raise RuntimeError(
        "Instala uma versao recente do supabase-py: "
        "pip install -r edge-device/requirements.txt"
    ) from exc

try:
    import certifi
except ImportError:
    certifi = None

if certifi is not None:
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())


SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://djeijlkqypvaznmlvtxe.supabase.co"
).strip()
SUPABASE_KEY = os.environ.get(
    "SUPABASE_KEY", "sb_publishable__gKHTQEwUBtQqcMi0-XNiQ_cU4fpPAN"
).strip()
SUPABASE_AUTH_JWT = os.environ.get("SUPABASE_AUTH_JWT", "")
AQL_DEVICE_TOKEN = os.environ.get("AQL_DEVICE_TOKEN", "")

KIT_ID = os.environ.get("AQL_KIT_ID", "")
KIT_NAME = os.environ.get("AQL_KIT_NAME", "MAC MINI M2")
DEVICE_ID = os.environ.get("AQL_DEVICE_ID", "")
DEVICE_NAME = os.environ.get("AQL_DEVICE_NAME", "")
CAMERA_ID = os.environ.get("AQL_CAMERA_ID", "")
CAMERA_CODE = os.environ.get("AQL_CAMERA_CODE", "cam-4341739a")

CAMERA_INDEX = int(os.environ.get("AQL_CAMERA_INDEX", "0"))
CAMERA_BACKEND = os.environ.get("AQL_CAMERA_BACKEND", "picamera2").strip().lower()
CAMERA_WIDTH = int(os.environ.get("AQL_CAMERA_WIDTH", "1920"))
CAMERA_HEIGHT = int(os.environ.get("AQL_CAMERA_HEIGHT", "1080"))
CAPTURES_BUCKET = os.environ.get("AQL_CAPTURES_BUCKET", "captures")
LIVE_FRAME_PATH = os.environ.get("AQL_LIVE_FRAME_PATH", f"live/{CAMERA_CODE}/feed.jpg")
QUEUE_DIR = Path(os.environ.get("AQL_QUEUE_DIR", str(Path.home() / "aql-vision-queue")))
QUEUE_MAX_BYTES = int(os.environ.get("AQL_QUEUE_MAX_BYTES", str(5 * 1024 * 1024 * 1024)))
QUEUE_MIN_FREE_BYTES = int(os.environ.get("AQL_QUEUE_MIN_FREE_BYTES", str(512 * 1024 * 1024)))
UPLOAD_RETRY_SECONDS = float(os.environ.get("AQL_UPLOAD_RETRY_SECONDS", "2"))

DEFAULT_FRAME_INTERVAL_MS = int(os.environ.get("AQL_FRAME_INTERVAL_MS", "100"))
JPEG_QUALITY = int(os.environ.get("AQL_JPEG_QUALITY", "70"))
HEARTBEAT_INTERVAL_SECONDS = int(os.environ.get("AQL_HEARTBEAT_INTERVAL_SECONDS", "120"))
UPLOAD_MODE = os.environ.get("AQL_UPLOAD_MODE", "function").strip().lower()
MODEL_DIR = Path(os.environ.get("AQL_MODEL_DIR", "/var/lib/aql-vision/models"))
MODEL_SYNC_INTERVAL_SECONDS = max(60, int(os.environ.get("AQL_MODEL_SYNC_INTERVAL_SECONDS", "300")))
MODEL_CONFIDENCE = min(1.0, max(0.01, float(os.environ.get("AQL_MODEL_CONFIDENCE", "0.35"))))
MODEL_NMS_THRESHOLD = min(1.0, max(0.01, float(os.environ.get("AQL_MODEL_NMS_THRESHOLD", "0.45"))))
MODEL_RESOLVE_URL = os.environ.get(
    "AQL_MODEL_RESOLVE_URL", f"{SUPABASE_URL}/functions/v1/vision-kit-model"
).strip()
ALERT_EVALUATOR_URL = os.environ.get(
    "AQL_ALERT_EVALUATOR_URL", f"{SUPABASE_URL}/functions/v1/vision-alert-rules"
).strip()
AGENT_VERSION = "2.2.2"
AGENT_UPDATE_MANIFEST_URL = os.environ.get(
    "AQL_AGENT_UPDATE_MANIFEST_URL",
    "https://www.aqlvision.com/edge-agent/latest.json",
).strip()
AGENT_UPDATE_INTERVAL_SECONDS = max(
    300, int(os.environ.get("AQL_AGENT_UPDATE_INTERVAL_SECONDS", "900"))
)
AGENT_UPDATE_ENABLED = os.environ.get("AQL_AGENT_UPDATE_ENABLED", "true").strip().lower() not in {
    "0", "false", "no", "off"
}


def supabase_function_headers(content_type: str | None = "application/json") -> dict[str, str]:
    headers = {
        "apikey": SUPABASE_KEY,
    }
    auth_jwt = SUPABASE_AUTH_JWT or (SUPABASE_KEY if SUPABASE_KEY.count(".") == 2 else "")
    if auth_jwt:
        headers["Authorization"] = f"Bearer {auth_jwt}"
    if content_type:
        headers["content-type"] = content_type
    if AQL_DEVICE_TOKEN:
        headers["x-aql-device-token"] = AQL_DEVICE_TOKEN
    return headers


def http_error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except Exception:
        body = response.text
    return f"{response.status_code} {response.reason_phrase}: {body}"


def raise_for_status_with_detail(response: httpx.Response) -> None:
    if response.is_error:
        raise RuntimeError(http_error_detail(response))


def configure_ssl_certificates() -> None:
    if os.environ.get("SSL_CERT_FILE"):
        return
    if certifi is None:
        return

    ca_path = certifi.where()
    os.environ.setdefault("SSL_CERT_FILE", ca_path)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_path)
    ssl.get_default_verify_paths()


def validate_supabase_key() -> None:
    if not SUPABASE_KEY:
        raise RuntimeError("Define SUPABASE_KEY no ambiente antes de arrancar o edge device.")

    if SUPABASE_KEY.startswith("sb_secret_"):
        raise RuntimeError(
            "SUPABASE_KEY esta no formato sb_secret_*. "
            "Nao uses secret/service-role keys no edge device. Usa uma publishable key ou uma anon public key com RLS adequado."
        )

    if not (SUPABASE_KEY.startswith("sb_publishable_") or SUPABASE_KEY.count(".") == 2):
        raise RuntimeError(
            "SUPABASE_KEY nao parece ser publishable nem anon JWT. "
            "Usa uma key sb_publishable_* ou a anon public JWT legacy."
        )


def clamp_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(float(value["value"] if isinstance(value, dict) and "value" in value else value))
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))


def queued_frames() -> list[Path]:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(QUEUE_DIR.glob("*.jpg"), key=lambda path: path.name)


def queue_size_bytes(files: list[Path] | None = None) -> int:
    total = 0
    for path in files if files is not None else queued_frames():
        try:
            total += path.stat().st_size
        except FileNotFoundError:
            pass
    return total


def persist_frame(img_bytes: bytes) -> Path:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp_ns = time.time_ns()
    final_path = QUEUE_DIR / f"{timestamp_ns:020d}.jpg"
    temporary_path = QUEUE_DIR / f".{timestamp_ns:020d}.tmp"
    with temporary_path.open("wb") as handle:
        handle.write(img_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary_path, final_path)
    return final_path


def queue_has_capacity(next_frame_size: int) -> bool:
    try:
        free_bytes = shutil.disk_usage(QUEUE_DIR).free
    except FileNotFoundError:
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        free_bytes = shutil.disk_usage(QUEUE_DIR).free
    return (
        queue_size_bytes() + next_frame_size <= QUEUE_MAX_BYTES
        and free_bytes - next_frame_size >= QUEUE_MIN_FREE_BYTES
    )


def seconds_to_frame_interval_ms(value: Any, fallback: int) -> int:
    try:
        raw = value["value"] if isinstance(value, dict) and "value" in value else value
        parsed = int(float(raw) * 1000)
    except (TypeError, ValueError):
        return fallback
    return max(50, min(60000, parsed))


@dataclass
class RuntimeState:
    kit_id: str = KIT_ID
    kit_name: str = KIT_NAME
    device_id: str = DEVICE_ID
    device_name: str = DEVICE_NAME
    camera_id: str = CAMERA_ID
    camera_code: str = CAMERA_CODE
    frame_interval_ms: int = DEFAULT_FRAME_INTERVAL_MS
    heartbeat_interval_seconds: int = HEARTBEAT_INTERVAL_SECONDS
    storage_bucket: str = CAPTURES_BUCKET
    live_frame_path: str = LIVE_FRAME_PATH
    jpg_quality: int = JPEG_QUALITY
    running: bool = True
    capture_requested: bool = False
    model_project_id: str = ""
    model_version: int = 0
    model_ready: bool = False
    realtime_connected: bool = False

    def apply_config_row(self, row: dict[str, Any]) -> None:
        if not row or row.get("is_enabled") is False:
            return

        key = str(row.get("config_key") or "")
        value = row.get("config_value")

        if key in {"frame_interval_ms", "camera_frame_interval_ms"}:
            self.frame_interval_ms = clamp_int(value, self.frame_interval_ms, 50, 60000)
            print(f"[config] frame_interval_ms={self.frame_interval_ms}")
        elif key in {"capture_interval_seconds", "captureIntervalSeconds"}:
            self.frame_interval_ms = seconds_to_frame_interval_ms(value, self.frame_interval_ms)
            print(f"[config] capture_interval_seconds -> frame_interval_ms={self.frame_interval_ms}")
        elif key == f"camera.{self.camera_code}.frame_interval_ms":
            self.frame_interval_ms = clamp_int(value, self.frame_interval_ms, 50, 60000)
            print(f"[config] {key}={self.frame_interval_ms}")
        elif key == f"camera.{self.camera_code}.capture_interval_seconds":
            self.frame_interval_ms = seconds_to_frame_interval_ms(value, self.frame_interval_ms)
            print(f"[config] {key} -> frame_interval_ms={self.frame_interval_ms}")
        elif key in {"storage_bucket", "live_capture_bucket"}:
            self.storage_bucket = str(value.get("value") if isinstance(value, dict) else value or self.storage_bucket)
            print(f"[config] storage_bucket={self.storage_bucket}")
        elif key in {"live_frame_path", "live_feed_path"}:
            self.live_frame_path = str(value.get("value") if isinstance(value, dict) else value or self.live_frame_path)
            print(f"[config] live_frame_path={self.live_frame_path}")
        elif key == "live_frame_path_template":
            template = str(value.get("value") if isinstance(value, dict) else value or "")
            if template:
                self.live_frame_path = template.format(camera_code=self.camera_code, camera_id=self.camera_id)
                print(f"[config] live_frame_path={self.live_frame_path}")
        elif key in {"jpg_quality", "jpeg_quality"}:
            self.jpg_quality = clamp_int(value, self.jpg_quality, 30, 95)
            print(f"[config] jpg_quality={self.jpg_quality}")
        elif key == f"camera.{self.camera_code}.storage_bucket":
            self.storage_bucket = str(value.get("value") if isinstance(value, dict) else value or self.storage_bucket)
            print(f"[config] {key}={self.storage_bucket}")
        elif key in {f"camera.{self.camera_code}.live_frame_path", f"camera.{self.camera_code}.live_feed_path"}:
            self.live_frame_path = str(value.get("value") if isinstance(value, dict) else value or self.live_frame_path)
            print(f"[config] {key}={self.live_frame_path}")

    @property
    def live_folder(self) -> str:
        parts = self.live_frame_path.split("/")
        if len(parts) >= 2 and parts[0] == "live":
            return parts[1]
        return self.camera_code

    def apply_heartbeat_response(self, body: dict[str, Any]) -> None:
        if body.get("kit_id"):
            self.kit_id = str(body["kit_id"])

        config = body.get("config") or {}
        self.frame_interval_ms = clamp_int(
            config.get("frame_interval_ms"),
            seconds_to_frame_interval_ms(config.get("capture_interval_seconds"), self.frame_interval_ms),
            50,
            60000,
        )
        self.storage_bucket = str(config.get("storage_bucket") or config.get("live_capture_bucket") or self.storage_bucket)
        self.jpg_quality = clamp_int(config.get("jpg_quality"), self.jpg_quality, 30, 95)

        cameras = config.get("cameras") or []
        if cameras:
            camera_config = next(
                (
                    item for item in cameras
                    if (self.camera_id and str(item.get("camera_id") or "") == self.camera_id)
                    or (self.camera_code and str(item.get("camera_code") or "").lower() == self.camera_code.lower())
                ),
                cameras[0],
            )
            self.camera_id = str(camera_config.get("camera_id") or self.camera_id)
            self.camera_code = str(camera_config.get("camera_code") or self.camera_code)
            self.frame_interval_ms = clamp_int(
                camera_config.get("frame_interval_ms"),
                seconds_to_frame_interval_ms(camera_config.get("capture_interval_seconds"), self.frame_interval_ms),
                50,
                60000,
            )
            self.storage_bucket = str(camera_config.get("storage_bucket") or self.storage_bucket)
            self.live_frame_path = str(camera_config.get("live_frame_path") or camera_config.get("live_feed_path") or self.live_frame_path)

        for key, value in (config.get("settings") or {}).items():
            self.apply_config_row({"config_key": key, "config_value": value, "is_enabled": True})


def heartbeat_payload(state: RuntimeState) -> dict[str, Any]:
    return {
        "kit_id": state.kit_id or None,
        "kit_name": state.kit_name or None,
        "kitName": state.kit_name or None,
        "kit": state.kit_name or None,
        "device_id": state.device_id or None,
        "device_name": state.device_name or None,
        "deviceName": state.device_name or None,
        "camera_id": state.camera_id or None,
        "camera_code": state.camera_code,
        "cameraCode": state.camera_code,
        "camera_ids": [state.camera_id] if state.camera_id else [],
        "camera_codes": [state.camera_code] if state.camera_code else [],
        "cameraCodes": [state.camera_code] if state.camera_code else [],
        "status": "online",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "metadata": {
            "agent": "aql-vision-raspberry",
            "agent_version": AGENT_VERSION,
            "model_project_id": state.model_project_id or None,
            "model_version": state.model_version or None,
            "model_ready": state.model_ready,
        },
    }


async def fetch_initial_config(state: RuntimeState) -> None:
    if not state.kit_id and not state.kit_name:
        print("[heartbeat] AQL_KIT_ID/AQL_KIT_NAME vazios; a saltar snapshot inicial.")
        return

    payload = heartbeat_payload(state)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{SUPABASE_URL}/functions/v1/vision-device-heartbeat",
                headers=supabase_function_headers(),
                json=payload,
            )
            raise_for_status_with_detail(response)
            body = response.json()
    except Exception as exc:
        print(f"[heartbeat] snapshot inicial falhou: {exc}")
        return

    state.apply_heartbeat_response(body)

    print(
        "[heartbeat] config inicial: "
        f"kit_id={state.kit_id or 'n/a'}, camera_id={state.camera_id or 'n/a'}, "
        f"frame_interval_ms={state.frame_interval_ms}, "
        f"heartbeat_interval_seconds={state.heartbeat_interval_seconds}, "
        f"bucket={state.storage_bucket}, path={state.live_frame_path}"
    )


async def send_heartbeat(state: RuntimeState) -> None:
    if not state.kit_id and not state.kit_name:
        return

    payload = heartbeat_payload(state)
    payload["camera_ok"] = True
    payload["metadata"] = {
        "agent": "aql-vision-raspberry",
        "agent_version": AGENT_VERSION,
        "camera_code": state.camera_code,
        "live_frame_path": state.live_frame_path,
        "storage_bucket": state.storage_bucket,
        "frame_interval_ms": state.frame_interval_ms,
        "jpg_quality": state.jpg_quality,
        "model_project_id": state.model_project_id or None,
        "model_version": state.model_version or None,
        "model_ready": state.model_ready,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{SUPABASE_URL}/functions/v1/vision-device-heartbeat",
                headers=supabase_function_headers(),
                json=payload,
            )
            raise_for_status_with_detail(response)
            body = response.json()
    except Exception as exc:
        print(f"[heartbeat] erro: {exc}")
        return

    previous_frame_interval_ms = state.frame_interval_ms
    previous_heartbeat_interval_seconds = state.heartbeat_interval_seconds
    previous_live_frame_path = state.live_frame_path

    state.apply_heartbeat_response(body)

    if (
        state.frame_interval_ms != previous_frame_interval_ms
        or state.heartbeat_interval_seconds != previous_heartbeat_interval_seconds
        or state.live_frame_path != previous_live_frame_path
    ):
        print(
            "[heartbeat] config atualizada: "
            f"frame_interval_ms={state.frame_interval_ms}, "
            f"heartbeat_interval_seconds={state.heartbeat_interval_seconds}, "
            f"path={state.live_frame_path}"
        )

    for command in body.get("commands") or []:
        command_type = command.get("command_type")
        if command_type == "capture_frame":
            state.capture_requested = True
            print(f"[command] capture_frame recebido: {command.get('command_id')}")
        elif command_type == "refresh_config":
            await fetch_initial_config(state)
            print(f"[command] refresh_config recebido: {command.get('command_id')}")
        elif command_type == "reboot_device":
            print("[command] reboot_device recebido; não executado automaticamente neste script.")


async def heartbeat_loop(state: RuntimeState) -> None:
    while state.running:
        try:
            await send_heartbeat(state)
        except Exception as exc:
            print(
                "[heartbeat] falhou; a captura e o buffer continuam ativos. "
                f"Nova tentativa mais tarde: {exc}"
            )
        await asyncio.sleep(state.heartbeat_interval_seconds)


async def upload_frame_via_function(img_bytes: bytes, state: RuntimeState) -> None:
    params = {"camera_code": state.camera_code}
    if state.kit_id:
        params["kit_id"] = state.kit_id
    if state.camera_id:
        params["camera_id"] = state.camera_id

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{SUPABASE_URL}/functions/v1/vision-captures/live",
            params=params,
            headers=supabase_function_headers("image/jpeg"),
            content=img_bytes,
        )
        raise_for_status_with_detail(response)


async def upload_buffer_frame(img_bytes: bytes, state: RuntimeState, captured_at: str) -> str | None:
    files = {"image": ("frame.jpg", img_bytes, "image/jpeg")}
    data = {
        "kit_id": state.kit_id,
        "camera_id": state.camera_id,
        "captured_at": captured_at,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{SUPABASE_URL}/functions/v1/vision-captures/upload",
            headers=supabase_function_headers(None),
            data=data,
            files=files,
        )
        raise_for_status_with_detail(response)
        return response.json().get("image_url")


async def upload_frame_via_storage(supabase: AsyncClient, img_bytes: bytes, state: RuntimeState) -> None:
    await supabase.storage.from_(state.storage_bucket).upload(
        path=state.live_frame_path,
        file=img_bytes,
        file_options={
            "cache-control": "0",
            "upsert": "true",
            "content-type": "image/jpeg",
        },
    )


def handle_config_change(state: RuntimeState, payload: Any) -> None:
    row = getattr(payload, "record", None) or (payload.get("record") if isinstance(payload, dict) else None)
    if not row:
        return

    row_kit_id = row.get("kit_id")
    row_device_id = row.get("device_id")
    row_camera_id = row.get("camera_id")

    if row_kit_id and state.kit_id and row_kit_id != state.kit_id:
        return
    if row_device_id and state.device_id and row_device_id != state.device_id:
        return
    if row_camera_id and state.camera_id and row_camera_id != state.camera_id:
        return

    state.apply_config_row(row)


def command_matches_state(state: RuntimeState, row: dict[str, Any]) -> bool:
    row_kit_id = row.get("kit_id")
    row_device_id = row.get("device_id")
    row_camera_id = row.get("camera_id")

    matches_kit = bool(row_kit_id and state.kit_id and row_kit_id == state.kit_id)
    matches_device = bool(row_device_id and state.device_id and row_device_id == state.device_id)
    matches_camera = bool(row_camera_id and state.camera_id and row_camera_id == state.camera_id)
    return matches_kit or matches_device or matches_camera


def camera_matches_state(state: RuntimeState, row: dict[str, Any]) -> bool:
    row_camera_id = row.get("camera_id")
    row_camera_code = row.get("camera_code")
    row_kit_id = row.get("kit_id")

    matches_camera_id = bool(row_camera_id and state.camera_id and row_camera_id == state.camera_id)
    matches_camera_code = bool(
        row_camera_code
        and state.camera_code
        and str(row_camera_code).lower() == state.camera_code.lower()
    )
    matches_kit = bool(row_kit_id and state.kit_id and row_kit_id == state.kit_id)
    return matches_camera_id or matches_camera_code or matches_kit


def kit_matches_state(state: RuntimeState, row: dict[str, Any]) -> bool:
    row_kit_id = row.get("kit_id")
    row_kit_name = row.get("name")
    matches_kit_id = bool(row_kit_id and state.kit_id and row_kit_id == state.kit_id)
    matches_kit_name = bool(row_kit_name and state.kit_name and row_kit_name == state.kit_name)
    return matches_kit_id or matches_kit_name


def payload_record(payload: Any) -> dict[str, Any] | None:
    return getattr(payload, "record", None) or (payload.get("record") if isinstance(payload, dict) else None)


def payload_old_record(payload: Any) -> dict[str, Any] | None:
    return getattr(payload, "old_record", None) or (payload.get("old_record") if isinstance(payload, dict) else None)


def relevant_fields_changed(payload: Any, fields: set[str]) -> bool:
    row = payload_record(payload)
    old_row = payload_old_record(payload)
    if not row:
        return False
    if not old_row:
        return True
    return any(row.get(field) != old_row.get(field) for field in fields)


def handle_command_change(state: RuntimeState, payload: Any) -> str | None:
    row = payload_record(payload)
    if not row or row.get("status") not in {"queued", "acknowledged"}:
        return None

    if not command_matches_state(state, row):
        return None

    if row.get("command_type") == "capture_frame":
        state.capture_requested = True
        print(f"[command] capture_frame recebido via realtime: {row.get('command_id')}")
        return None
    elif row.get("command_type") == "refresh_config":
        print("[command] refresh_config recebido via realtime.")
        return "refresh_config"
    return None


async def realtime_loop(supabase: AsyncClient, state: RuntimeState) -> None:
    def on_config(payload: Any) -> None:
        handle_config_change(state, payload)

    def on_command(payload: Any) -> None:
        action = handle_command_change(state, payload)
        if action == "refresh_config":
            asyncio.create_task(fetch_initial_config(state))

    def on_camera(payload: Any) -> None:
        row = payload_record(payload)
        config_changed = relevant_fields_changed(
            payload,
            {
                "camera_code",
                "capture_interval_seconds",
                "frame_interval_ms",
                "is_active",
                "kit_id",
                "live_feed_path",
                "source_uri",
            },
        )
        if row and config_changed and camera_matches_state(state, row):
            print("[realtime] alteração na câmara; a refrescar config.")
            asyncio.create_task(fetch_initial_config(state))

    def on_kit(payload: Any) -> None:
        row = payload_record(payload)
        config_changed = relevant_fields_changed(
            payload,
            {
                "capture_interval_seconds",
                "edge_runtime_config",
                "frame_interval_ms",
                "live_capture_bucket",
                "name",
            },
        )
        if row and config_changed and kit_matches_state(state, row):
            print("[realtime] alteração no kit; a refrescar config.")
            asyncio.create_task(fetch_initial_config(state))

    while state.running:
        channel = None
        try:
            presence_key = state.device_id or state.kit_id or state.camera_code
            connection_lost = asyncio.Event()
            channel = supabase.channel(
                f"aql-edge-{state.kit_id or state.kit_name or state.camera_code}",
                {"config": {"presence": {"key": presence_key}}},
            )

            async def publish_presence() -> None:
                await channel.track({
                    "agent": "aql-vision-raspberry",
                    "agent_version": AGENT_VERSION,
                    "kit_id": state.kit_id or None,
                    "device_id": state.device_id or None,
                    "camera_id": state.camera_id or None,
                    "online_at": datetime.now(timezone.utc).isoformat(),
                })
                await send_heartbeat(state)

            def on_subscribe(status: Any, error: Any = None) -> None:
                status_name = str(getattr(status, "value", status)).split(".")[-1].upper()
                if status_name == "SUBSCRIBED":
                    state.realtime_connected = True
                    asyncio.create_task(publish_presence())
                    print("[realtime] presença online publicada.")
                elif status_name in {"CHANNEL_ERROR", "TIMED_OUT", "CLOSED"}:
                    state.realtime_connected = False
                    print(f"[realtime] canal {status_name.lower()}: {error or 'sem detalhe'}")
                    connection_lost.set()

            await (
                channel
                .on_presence_sync(callback=lambda: None)
                .on_postgres_changes(
                    "*",
                    schema="public",
                    table="aql_device_runtime_configs",
                    callback=on_config,
                )
                .on_postgres_changes(
                    "*",
                    schema="public",
                    table="aql_device_commands",
                    callback=on_command,
                )
                .on_postgres_changes(
                    "*",
                    schema="public",
                    table="aql_cameras",
                    callback=on_camera,
                )
                .on_postgres_changes(
                    "*",
                    schema="public",
                    table="aql_kits",
                    callback=on_kit,
                )
                .subscribe(on_subscribe)
            )
            print("[realtime] subscrito a configs/comandos/camaras/kits.")
            await connection_lost.wait()
        except Exception as exc:
            state.realtime_connected = False
            print(f"[realtime] ligação falhou: {exc}. A tentar novamente...")
        finally:
            state.realtime_connected = False
            if channel is not None:
                try:
                    await supabase.remove_channel(channel)
                except Exception:
                    pass
        if state.running:
            await asyncio.sleep(2)


def encode_frame(frame: Any, jpg_quality: int) -> bytes | None:
    ok, img_encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), jpg_quality])
    if not ok:
        return None
    return img_encoded.tobytes()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def version_tuple(value: Any) -> tuple[int, ...]:
    parts = []
    for part in str(value or "0").split("."):
        digits = "".join(character for character in part if character.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


async def agent_update_loop(state: RuntimeState) -> None:
    if not AGENT_UPDATE_ENABLED or not AGENT_UPDATE_MANIFEST_URL:
        print("[update] atualizacoes automaticas desativadas.")
        return

    while state.running:
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                manifest_response = await client.get(
                    AGENT_UPDATE_MANIFEST_URL,
                    params={"current": AGENT_VERSION, "ts": int(time.time())},
                )
                raise_for_status_with_detail(manifest_response)
                manifest = manifest_response.json()
                latest_version = str(manifest.get("version") or "0")
                if version_tuple(latest_version) > version_tuple(AGENT_VERSION):
                    download_url = str(manifest.get("url") or "").strip()
                    expected_hash = str(manifest.get("sha256") or "").strip().lower()
                    if not download_url or len(expected_hash) != 64:
                        raise RuntimeError("Manifesto de atualizacao incompleto.")
                    download_response = await client.get(download_url)
                    raise_for_status_with_detail(download_response)
                    payload = download_response.content
                    actual_hash = hashlib.sha256(payload).hexdigest()
                    if actual_hash != expected_hash:
                        raise RuntimeError("Hash da atualizacao do agente nao corresponde.")
                    source = payload.decode("utf-8")
                    compile(source, download_url, "exec")

                    current_path = Path(__file__).resolve()
                    incoming_path = current_path.with_suffix(".py.update")
                    previous_path = current_path.with_suffix(".py.previous")
                    await asyncio.to_thread(incoming_path.write_bytes, payload)
                    os.chmod(incoming_path, stat.S_IMODE(current_path.stat().st_mode))
                    if previous_path.exists():
                        previous_path.unlink()
                    os.replace(current_path, previous_path)
                    os.replace(incoming_path, current_path)
                    print(
                        f"[update] agente {AGENT_VERSION} atualizado para {latest_version}; "
                        "a reiniciar automaticamente."
                    )
                    os._exit(75)
                print(f"[update] agente {AGENT_VERSION} atualizado.")
        except Exception as exc:
            print(f"[update] verificacao falhou; nova tentativa mais tarde: {exc}")
        await asyncio.sleep(AGENT_UPDATE_INTERVAL_SECONDS)


def captured_at_from_path(path: Path) -> str:
    try:
        timestamp_ns = int(path.stem)
        return datetime.fromtimestamp(timestamp_ns / 1_000_000_000, timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, OSError, OverflowError):
        return utc_now()


def class_names(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        return [str(value[key]) for key in sorted(value, key=lambda item: int(item) if str(item).isdigit() else str(item))]
    return []


class EdgeModel:
    def __init__(self, path: Path, metadata: dict[str, Any]) -> None:
        self.net = cv2.dnn.readNetFromONNX(str(path))
        self.metadata = metadata
        self.classes = class_names(metadata.get("classes"))
        self.imgsz = clamp_int(metadata.get("imgsz"), 640, 160, 2048)

    def infer(self, jpeg: bytes) -> tuple[list[dict[str, Any]], int, int]:
        encoded = cv2.imdecode(
            __import__("numpy").frombuffer(jpeg, dtype=__import__("numpy").uint8),
            cv2.IMREAD_COLOR,
        )
        if encoded is None:
            raise RuntimeError("Nao foi possivel abrir o frame para inferencia.")

        frame_height, frame_width = encoded.shape[:2]
        scale = min(self.imgsz / frame_width, self.imgsz / frame_height)
        resized_width = max(1, round(frame_width * scale))
        resized_height = max(1, round(frame_height * scale))
        resized = cv2.resize(encoded, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
        pad_x = (self.imgsz - resized_width) // 2
        pad_y = (self.imgsz - resized_height) // 2
        letterboxed = cv2.copyMakeBorder(
            resized,
            pad_y,
            self.imgsz - resized_height - pad_y,
            pad_x,
            self.imgsz - resized_width - pad_x,
            cv2.BORDER_CONSTANT,
            value=(114, 114, 114),
        )
        blob = cv2.dnn.blobFromImage(letterboxed, 1 / 255.0, (self.imgsz, self.imgsz), swapRB=True, crop=False)
        self.net.setInput(blob)
        output = self.net.forward()
        rows = output[0] if len(output.shape) == 3 else output
        if rows.shape[0] <= 5 + len(self.classes) and rows.shape[1] > rows.shape[0]:
            rows = rows.T

        boxes: list[list[int]] = []
        confidences: list[float] = []
        class_ids: list[int] = []
        expected_without_objectness = 4 + len(self.classes)
        for row in rows:
            if len(row) < expected_without_objectness:
                continue
            if len(row) == 5 + len(self.classes):
                scores = row[5:] * float(row[4])
            else:
                scores = row[4:4 + len(self.classes)]
            class_id = int(scores.argmax())
            confidence = float(scores[class_id])
            if confidence < MODEL_CONFIDENCE:
                continue
            center_x, center_y, width, height = (float(value) for value in row[:4])
            left = round((center_x - width / 2 - pad_x) / scale)
            top = round((center_y - height / 2 - pad_y) / scale)
            box_width = round(width / scale)
            box_height = round(height / scale)
            left = max(0, min(frame_width - 1, left))
            top = max(0, min(frame_height - 1, top))
            box_width = max(1, min(frame_width - left, box_width))
            box_height = max(1, min(frame_height - top, box_height))
            boxes.append([left, top, box_width, box_height])
            confidences.append(confidence)
            class_ids.append(class_id)

        selected = cv2.dnn.NMSBoxes(boxes, confidences, MODEL_CONFIDENCE, MODEL_NMS_THRESHOLD)
        indices = [int(item) for item in __import__("numpy").array(selected).reshape(-1)] if len(selected) else []
        detections = []
        for index in indices:
            left, top, width, height = boxes[index]
            class_id = class_ids[index]
            detections.append({
                "class_id": class_id,
                "class_label": self.classes[class_id] if class_id < len(self.classes) else str(class_id),
                "confidence": round(confidences[index], 6),
                "bbox": {
                    "x": left,
                    "y": top,
                    "width": width,
                    "height": height,
                    "x1": left,
                    "y1": top,
                    "x2": left + width,
                    "y2": top + height,
                },
            })
        return detections, frame_width, frame_height


class ModelManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model: EdgeModel | None = None

    def install(self, path: Path, metadata: dict[str, Any]) -> None:
        model = EdgeModel(path, metadata)
        with self._lock:
            self._model = model

    def infer(self, jpeg: bytes) -> tuple[list[dict[str, Any]], int, int, dict[str, Any]] | None:
        with self._lock:
            model = self._model
            if model is None:
                return None
            detections, width, height = model.infer(jpeg)
            return detections, width, height, dict(model.metadata)


def load_current_model(manager: ModelManager, state: RuntimeState) -> None:
    model_path = MODEL_DIR / "current.onnx"
    metadata_path = MODEL_DIR / "current.json"
    if not model_path.exists() or not metadata_path.exists():
        return
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    manager.install(model_path, metadata)
    state.model_project_id = str(metadata.get("project_id") or "")
    state.model_version = int(metadata.get("version") or 0)
    state.model_ready = True
    print(f"[model] ONNX v{state.model_version} carregado do disco.")


async def sync_model(manager: ModelManager, state: RuntimeState) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            MODEL_RESOLVE_URL,
            headers=supabase_function_headers(),
            json={"kit_id": state.kit_id},
        )
        if response.status_code in {404, 409}:
            detail = response.json().get("error", "modelo indisponivel")
            print(f"[model] ainda nao configurado: {detail}")
            return
        raise_for_status_with_detail(response)
        release = response.json()

        project_id = str(release.get("project_id") or "")
        version = int(release.get("version") or 0)
        current_path = MODEL_DIR / "current.onnx"
        metadata_path = MODEL_DIR / "current.json"
        if state.model_ready and state.model_project_id == project_id and state.model_version == version and current_path.exists():
            return

        download = await client.get(str(release["download_url"]), timeout=120)
        raise_for_status_with_detail(download)

    payload = download.content
    expected_size = int(release.get("size") or 0)
    expected_hash = str(release.get("sha256") or "").lower()
    actual_hash = hashlib.sha256(payload).hexdigest()
    if expected_size and len(payload) != expected_size:
        raise RuntimeError(f"Tamanho ONNX invalido: esperado {expected_size}, recebido {len(payload)}.")
    if expected_hash and actual_hash != expected_hash:
        raise RuntimeError("A verificacao SHA-256 do ONNX falhou.")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    incoming_path = MODEL_DIR / "incoming.onnx"
    await asyncio.to_thread(incoming_path.write_bytes, payload)
    metadata = {
        key: release.get(key)
        for key in ("project_id", "policy", "version", "sha256", "size", "task", "classes", "imgsz")
    }
    await asyncio.to_thread(manager.install, incoming_path, metadata)
    previous_path = MODEL_DIR / "previous.onnx"
    if current_path.exists():
        os.replace(current_path, previous_path)
    os.replace(incoming_path, current_path)
    pending_metadata = MODEL_DIR / "current.json.tmp"
    pending_metadata.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    os.replace(pending_metadata, metadata_path)
    state.model_project_id = project_id
    state.model_version = version
    state.model_ready = True
    print(f"[model] ONNX v{version} verificado e ativado ({actual_hash[:12]}...).")


async def model_sync_loop(manager: ModelManager, state: RuntimeState) -> None:
    try:
        await asyncio.to_thread(load_current_model, manager, state)
    except Exception as exc:
        print(f"[model] modelo guardado nao carregou: {exc}")
    while state.running:
        try:
            await sync_model(manager, state)
        except Exception as exc:
            print(f"[model] sincronizacao falhou; a camera continua ativa: {exc}")
        await asyncio.sleep(MODEL_SYNC_INTERVAL_SECONDS)


async def publish_detections(
    state: RuntimeState,
    detections: list[dict[str, Any]],
    width: int,
    height: int,
    metadata: dict[str, Any],
    captured_at: str,
    image_url: str | None = None,
) -> None:
    resolved_image_url = image_url or (
        f"{SUPABASE_URL}/storage/v1/object/public/{state.storage_bucket}/{state.live_frame_path}"
    )
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            ALERT_EVALUATOR_URL,
            headers=supabase_function_headers(),
            json={
                "kit_id": state.kit_id,
                "camera_id": state.camera_id,
                "image_url": resolved_image_url,
                "captured_at": captured_at,
                "frame": {"width": width, "height": height},
                "model": {
                    "project_id": metadata.get("project_id"),
                    "version": metadata.get("version"),
                },
                "detections": detections,
            },
        )
        raise_for_status_with_detail(response)


class CameraSource:
    def __init__(self) -> None:
        self.picamera = None
        self.opencv = None

    def start(self) -> None:
        if CAMERA_BACKEND == "picamera2":
            if Picamera2 is None:
                raise RuntimeError(
                    "Picamera2 nao esta instalado. Corre: sudo apt install -y python3-picamera2"
                )
            self.picamera = Picamera2()
            config = self.picamera.create_video_configuration(
                main={"size": (CAMERA_WIDTH, CAMERA_HEIGHT), "format": "RGB888"}
            )
            self.picamera.configure(config)
            try:
                from libcamera import controls

                self.picamera.set_controls({
                    "AfMode": controls.AfModeEnum.Continuous,
                    "AfRange": controls.AfRangeEnum.Normal,
                    "AwbMode": controls.AwbModeEnum.Auto,
                })
                print("[camera] autofoco continuo e balanco de brancos automatico ativados.")
            except Exception as enum_exc:
                try:
                    self.picamera.set_controls({"AfMode": 2, "AfRange": 0})
                    print("[camera] autofoco continuo ativado em modo compatibilidade.")
                except Exception as fallback_exc:
                    print(
                        "[camera] controlos de autofoco indisponiveis; "
                        f"a captura continua sem AF continuo: {fallback_exc} "
                        f"(enums: {enum_exc})"
                    )
            self.picamera.start()
            time.sleep(2)
            return

        if CAMERA_BACKEND != "opencv":
            raise RuntimeError("AQL_CAMERA_BACKEND deve ser 'picamera2' ou 'opencv'.")
        self.opencv = cv2.VideoCapture(CAMERA_INDEX)
        if not self.opencv.isOpened():
            raise RuntimeError("Nao foi possivel aceder a camera OpenCV.")

    def capture(self, jpg_quality: int) -> bytes | None:
        if self.picamera is not None:
            return encode_frame(self.picamera.capture_array("main"), jpg_quality)
        if self.opencv is not None:
            ret, frame = self.opencv.read()
            return encode_frame(frame, jpg_quality) if ret else None
        return None

    def close(self) -> None:
        if self.picamera is not None:
            self.picamera.stop()
            self.picamera.close()
        if self.opencv is not None:
            self.opencv.release()


async def camera_capture_loop(state: RuntimeState) -> None:
    camera = CameraSource()
    await asyncio.to_thread(camera.start)

    print(
        "[camera] iniciada. "
        f"backend={CAMERA_BACKEND}, resolucao={CAMERA_WIDTH}x{CAMERA_HEIGHT}, "
        f"frame_interval_ms={state.frame_interval_ms}, queue={QUEUE_DIR}"
    )

    try:
        while state.running:
            cycle_started = time.monotonic()
            img_bytes = await asyncio.to_thread(camera.capture, state.jpg_quality)
            if not img_bytes:
                print("[camera] erro ao ler/encodar frame.")
                await asyncio.sleep(0.3)
                continue

            if queue_has_capacity(len(img_bytes)):
                try:
                    queued_path = await asyncio.to_thread(persist_frame, img_bytes)
                    print(f"[camera] frame guardado: {queued_path.name}")
                except OSError as exc:
                    print(f"[camera] nao foi possivel guardar o frame no SD: {exc}")
            else:
                print(
                    "[camera] fila cheia ou espaco livre abaixo da reserva; "
                    "frame ignorado para proteger o cartao."
                )

            if state.capture_requested:
                state.capture_requested = False
                print("[camera] capture_frame satisfeito com o ultimo frame guardado.")

            elapsed = time.monotonic() - cycle_started
            await asyncio.sleep(max(0, state.frame_interval_ms / 1000 - elapsed))
    finally:
        await asyncio.to_thread(camera.close)


async def upload_queue_loop(supabase: AsyncClient, state: RuntimeState, models: ModelManager) -> None:
    prefer_live = True
    while state.running:
        files = await asyncio.to_thread(queued_frames)
        if not files:
            await asyncio.sleep(0.25)
            continue

        # Quando existe backlog alternamos entre o frame mais recente (painel live)
        # e o mais antigo (recuperacao historica). Assim o buffer e integralmente
        # inferido sem deixar o operador preso varios minutos no passado.
        is_live = len(files) == 1 or prefer_live
        path = files[-1] if is_live else files[0]
        prefer_live = not prefer_live
        try:
            img_bytes = await asyncio.to_thread(path.read_bytes)
            captured_at = captured_at_from_path(path)
            if is_live and UPLOAD_MODE == "storage":
                await upload_frame_via_storage(supabase, img_bytes, state)
                image_url = None
            elif is_live:
                await upload_frame_via_function(img_bytes, state)
                image_url = None
            else:
                image_url = await upload_buffer_frame(img_bytes, state, captured_at)
            inference = await asyncio.to_thread(models.infer, img_bytes)
            if inference is not None:
                detections, width, height, metadata = inference
                try:
                    await publish_detections(
                        state,
                        detections,
                        width,
                        height,
                        metadata,
                        captured_at,
                        image_url,
                    )
                    print(
                        f"[inference] ONNX v{metadata.get('version')}: "
                        f"{len(detections)} detecoes."
                    )
                except Exception as exc:
                    print(f"[inference] resultado nao enviado; a camera continua ativa: {exc}")
            path.unlink(missing_ok=True)
            lane = "live" if is_live else "buffer"
            print(f"[upload] {lane} confirmado e removido da fila: {path.name}; pendentes={len(files) - 1}")
        except Exception as exc:
            print(f"[upload] falhou; ficheiro mantido para retry: {path.name}: {exc}")
            await asyncio.sleep(max(0.5, UPLOAD_RETRY_SECONDS))


async def main() -> None:
    configure_ssl_certificates()
    validate_supabase_key()

    state = RuntimeState()
    models = ModelManager()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: setattr(state, "running", False))

    supabase = await acreate_client(SUPABASE_URL, SUPABASE_KEY)
    await fetch_initial_config(state)

    await asyncio.gather(
        realtime_loop(supabase, state),
        heartbeat_loop(state),
        model_sync_loop(models, state),
        agent_update_loop(state),
        camera_capture_loop(state),
        upload_queue_loop(supabase, state, models),
    )


if __name__ == "__main__":
    asyncio.run(main())
