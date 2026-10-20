"""Non-secret model selection and bounded access probe."""
import os
import json
from pathlib import Path
from datetime import datetime, timezone
import requests
import time
import random
import uuid

MODEL = "gemini-3.6-flash"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"


TRANSIENT = {408, 429, 500, 502, 503, 504}


def _record(result):
    path = Path("data/gemini_health.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    temp.write_text(json.dumps(result, indent=2), encoding="utf-8")
    temp.replace(path)


def generate(payload, key, operation="unknown", *, record_diagnostics=True):
    """Bounded retries plus secret-free diagnostics for the real chat request."""
    started = time.monotonic()
    request_id = uuid.uuid4().hex[:12]
    payload_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    last_error = None
    for attempt in range(4):
        try:
            response = requests.post(URL, headers={"x-goog-api-key": key}, json=payload, timeout=(10, 45))
            if response.status_code not in TRANSIENT or attempt == 3:
                error_status = None
                if response.status_code != 200:
                    try:
                        candidate = response.json().get("error", {}).get("status")
                        error_status = candidate if isinstance(candidate, str) else None
                    except (ValueError, AttributeError):
                        error_status = None
                result = {"request_id": request_id, "model": MODEL, "operation": operation,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "ok": response.status_code == 200, "http_status": response.status_code,
                    "api_error_status": error_status, "attempts": attempt + 1,
                    "duration_ms": round((time.monotonic()-started)*1000),
                    "payload_bytes": payload_bytes}
                if record_diagnostics:
                    _record(result)
                return response
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
            if attempt == 3:
                result = {"request_id": request_id, "model": MODEL, "operation": operation,
                    "checked_at": datetime.now(timezone.utc).isoformat(), "ok": False,
                    "exception_type": type(exc).__name__, "attempts": attempt + 1,
                    "duration_ms": round((time.monotonic()-started)*1000),
                    "payload_bytes": payload_bytes}
                if record_diagnostics:
                    _record(result)
                raise
        time.sleep((2**attempt) + random.uniform(0, 0.5))
    raise last_error or RuntimeError("Gemini request ended without response")


def probe_access_once():
    """Run in the normal worker environment; never load or expose credentials."""
    path = Path("data/gemini_access_3_6.json")
    key = os.getenv("GEMINI_API_KEY", "").strip()
    result = {"model": MODEL, "checked_at": datetime.now(timezone.utc).isoformat(),
              "ok": False, "status": "missing_key"}
    if key:
        try:
            response = requests.post(URL, headers={"x-goog-api-key": key},
                json={"contents": [{"parts": [{"text": "Reply only OK."}]}],
                      "generationConfig": {"maxOutputTokens": 256}}, timeout=30)
            result["http_status"] = response.status_code
            result["status"] = "http_error"
            if response.status_code == 200:
                parts = response.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                result["ok"] = any(p.get("text", "").strip() for p in parts if not p.get("thought"))
                result["status"] = "text_received" if result["ok"] else "empty_response"
        except Exception as exc:
            result["status"] = "request_failed"
            result["error_type"] = type(exc).__name__
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(result, indent=2), encoding="utf-8")
    temp.replace(path)


def probe_conversation():
    """Exercise the same request shape as chat, without user or portfolio data."""
    path = Path("data/gemini_conversation_probe.json")
    key = os.getenv("GEMINI_API_KEY", "").strip()
    result = {"model": MODEL, "checked_at": datetime.now(timezone.utc).isoformat(),
              "ok": False, "status": "missing_key"}
    if key:
        payload = {"contents": [{"parts": [{"text":
            "Kamu asisten crypto berbahasa Indonesia. Berdasarkan JSON ini, jawab satu kalimat: "
            '{"paper_portfolio":{"equity":1000,"net_pnl_usd":0},"binance_read_only":{"connected":false}}'}]}],
            "generationConfig": {"maxOutputTokens": 900}}
        try:
            response = generate(payload, key, operation="startup_probe")
            result["http_status"] = response.status_code
            if response.status_code == 200:
                parts = response.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                result["ok"] = any(p.get("text", "").strip() for p in parts if not p.get("thought"))
                result["status"] = "text_received" if result["ok"] else "empty_response"
            else:
                result["status"] = "http_error"
        except Exception as exc:
            result["status"] = "request_failed"
            result["error_type"] = type(exc).__name__
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(result, indent=2), encoding="utf-8")
    temp.replace(path)
