import json
import os
import re
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, Optional, cast

from openai import AzureOpenAI
from openai.types.chat import ChatCompletionMessageParam

from .config import (
    APP_TZ,
    TIMEZONE,
    azure_openai_api_key,
    azure_openai_api_version,
    azure_openai_deployment,
    azure_openai_endpoint,
    is_testing,
    logger,
    now_tz,
)

client: Optional[AzureOpenAI] = None
try:
    if azure_openai_api_key and azure_openai_endpoint and azure_openai_api_version:
        client = AzureOpenAI(
            api_key=cast(str, azure_openai_api_key),
            azure_endpoint=cast(str, azure_openai_endpoint),
            api_version=cast(str, azure_openai_api_version),
        )
        logger.info("Azure OpenAI client initialized")
    else:
        logger.warning("Azure OpenAI client not configured; LLM parsing unavailable")
except Exception as e:
    logger.warning(f"Failed to initialize Azure OpenAI client: {e}")
    if is_testing:
        from unittest.mock import MagicMock

        client = MagicMock()
        logger.info("Created mock Azure OpenAI client for testing")
    else:
        client = None

def _call_llm_only(text: str, current_iso_utc: str, prev_eta_iso: Optional[str]) -> Dict[str, Any]:
    import main  # type: ignore

    temp_dir = tempfile.gettempdir()
    log_file = os.path.join(temp_dir, "respondr_llm_debug.log")
    log_entry: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "input": {"text": text, "current_iso_utc": current_iso_utc, "prev_eta_iso": prev_eta_iso},
    }
    active_client = getattr(main, "client", client)
    if active_client is None:
        log_entry["error"] = "Azure OpenAI not configured"
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass
        return {"_llm_unavailable": True}
    model = cast(str, azure_openai_deployment or "gpt")
    try:
        msgs: list[ChatCompletionMessageParam] = [
            {
                "role": "system",
                "content": "Extract vehicle, eta_iso, status, evidence, and confidence as JSON.",
            },
            {
                "role": "user",
                "content": text,
            },
        ]
        resp = active_client.chat.completions.create(
            model=model,
            messages=msgs,
            temperature=0,
        )
        raw_content = resp.choices[0].message.content or ""
        return json.loads(raw_content) if raw_content else {}
    except Exception as e:
        logger.warning(f"LLM-only parse failed: {e}")
        log_entry["error"] = str(e)
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass
        return {"_llm_error": str(e)}

def _populate_eta_fields_from_llm_eta(eta_iso_or_unknown: str, message_time: datetime) -> Dict[str, Any]:
    if not eta_iso_or_unknown or str(eta_iso_or_unknown).strip() == "Unknown":
        return {
            "eta": "Unknown",
            "eta_timestamp": None,
            "eta_timestamp_utc": None,
            "minutes_until_arrival": None,
        }
    try:
        eta_dt_utc = datetime.fromisoformat(str(eta_iso_or_unknown).replace("Z", "+00:00")).astimezone(timezone.utc)
        eta_local = eta_dt_utc.astimezone(APP_TZ)
        eta_hhmm = eta_local.strftime("%H:%M")
        eta_ts_local = eta_local.strftime("%Y-%m-%d %H:%M:%S") if is_testing else eta_local.isoformat()
        minutes_until = int((eta_local - now_tz()).total_seconds() / 60)
        return {
            "eta": eta_hhmm,
            "eta_timestamp": eta_ts_local,
            "eta_timestamp_utc": eta_dt_utc.isoformat(),
            "minutes_until_arrival": minutes_until,
        }
    except Exception:
        logger.debug(f"Failed to parse eta_iso='{eta_iso_or_unknown}'")
        return {
            "eta": "Unknown",
            "eta_timestamp": None,
            "eta_timestamp_utc": None,
            "minutes_until_arrival": None,
        }

def extract_details_from_text(text: str, base_time: Optional[datetime] = None, prev_eta_iso: Optional[str] = None) -> Dict[str, Any]:
    anchor_time: datetime = base_time or now_tz()
    current_iso_utc = anchor_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    data = _call_llm_only(text, current_iso_utc, prev_eta_iso)
    if isinstance(data, dict) and (data.get("_llm_unavailable") or data.get("_llm_error")):
        return {
            "vehicle": "Unknown",
            "eta": "Unknown",
            "raw_status": "Unknown",
            "status_source": "LLM-Only",
            "status_confidence": 0.0,
            "eta_timestamp": None,
            "eta_timestamp_utc": None,
            "minutes_until_arrival": None,
            "parse_source": "LLM",
        }
    vehicle_raw = str(data.get("vehicle") or "Unknown") if isinstance(data, dict) else "Unknown"
    m_v = re.match(r"^\s*sar[\s-]?0*(\d{1,3})\s*$", vehicle_raw, flags=re.I)
    if m_v:
        vehicle = f"SAR-{int(m_v.group(1))}"
    elif vehicle_raw.strip().upper() in {"POV", "SAR RIG"}:
        vehicle = vehicle_raw.strip().upper().replace("SAR RIG", "SAR Rig")
    else:
        vehicle = vehicle_raw if vehicle_raw else "Unknown"
    status = str(data.get("status") or "Unknown") if isinstance(data, dict) else "Unknown"
    confidence_raw = data.get("confidence") if isinstance(data, dict) else 0.0
    try:
        status_confidence = float(confidence_raw or 0.0)
    except Exception:
        status_confidence = 0.0
    eta_iso = str(data.get("eta_iso") or "Unknown") if isinstance(data, dict) else "Unknown"
    eta_fields = _populate_eta_fields_from_llm_eta(eta_iso, anchor_time)
    return {
        "vehicle": vehicle,
        "eta": eta_fields["eta"],
        "raw_status": status,
        "status_source": "LLM-Only",
        "status_confidence": status_confidence,
        "eta_timestamp": eta_fields["eta_timestamp"],
        "eta_timestamp_utc": eta_fields["eta_timestamp_utc"],
        "minutes_until_arrival": eta_fields["minutes_until_arrival"],
        "parse_source": "LLM",
    }
