import json
import logging
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from openai import AzureOpenAI
from openai.types.chat import ChatCompletionMessageParam

from .config import (
    azure_openai_api_key, azure_openai_endpoint, azure_openai_deployment,
    azure_openai_api_version, DEBUG_FULL_LLM_LOG, TIMEZONE, APP_TZ
)
from .utils import extract_eta_from_text_local, extract_duration_eta, compute_eta_fields, now_tz

logger = logging.getLogger(__name__)

client = None
if azure_openai_api_key and azure_openai_endpoint:
    try:
        client = AzureOpenAI(
            api_key=azure_openai_api_key,
            api_version=azure_openai_api_version or "2024-02-01",
            azure_endpoint=azure_openai_endpoint,
        )
    except Exception as e:
        logger.error(f"Failed to initialize Azure OpenAI client: {e}")


def _normalize_vehicle_name(vehicle_raw: str) -> str:
    s = (vehicle_raw or "").strip()
    m = re.match(r"^\s*sar[\s-]?0*(\d{1,3})\s*$", s, re.I)
    if m:
        return f"SAR-{int(m.group(1))}"
    if s.upper() in {"POV", "SAR RIG"}:
        return s.upper().replace("SAR RIG", "SAR Rig")
    return s if s else "Unknown"


def _is_standdown(text: str) -> bool:
    s = (text or "").lower()
    phrases = [
        "standing down", "stand down", "10-22", "1022",
        "can't make it", "cannot make it", "won't make it",
        "cancelling", "canceled", "cancelled", "not responding",
        "returning", "turning around", "mission canceled", "mission cancelled",
        "subject found"
    ]
    return any(p in s for p in phrases)


def _select_kwargs_for_model(model_name: str) -> Dict[str, Any]:
    kw: Dict[str, Any] = {"max_completion_tokens": 768, "temperature": 1, "top_p": 1, "presence_penalty": 0, "frequency_penalty": 0}
    if re.search(r"gpt-5-(nano|mini)", model_name or "", re.I):
        kw["verbosity"] = "low"           # some models support this
        kw["reasoning_effort"] = "low"    # some models support this
    elif re.search(r"(gpt-5(?!-(nano|mini))|o3|gpt-4\.1)", model_name or "", re.I):
        kw["reasoning_effort"] = "medium"
    return kw


def _call_llm_only(text: str, base_dt: datetime, prev_eta_iso: Optional[str], llm_client=None) -> Dict[str, Any]:
    c = llm_client or client
    if not c:
        return {"_llm_unavailable": True}
    if not azure_openai_deployment:
        return {"_llm_error": "No deployment configured"}
    assert azure_openai_deployment is not None

    cur_utc = base_dt.astimezone(timezone.utc)
    cur_loc = base_dt.astimezone(APP_TZ)

    sys_msg = (
        "You analyze Search & Rescue response messages. Extract vehicle, ETA, and status. "
        "Assume all times in the message are LOCAL time unless explicitly marked otherwise. "
        f"Local timezone: {TIMEZONE}. Output MUST convert any local time to UTC ISO in `eta_iso`."
    )
    user_msg = (
        f"Current time (UTC): {cur_utc.isoformat().replace('+00:00','Z')}\n"
        f"Current time (Local {TIMEZONE}): {cur_loc.isoformat()}\n"
        f"Previous ETA (UTC, optional): {prev_eta_iso or 'None'}\n\n"
        f"Message: {text}\n\n"
        "Return ONLY JSON with keys: vehicle, eta_iso, status, confidence.\n"
        "Status rules:\n"
        "- Responding: actively responding / ETA updates from an already-responding person\n"
        "- Not Responding: stand down / 10-22 / 1022 / mission canceled acknowledgements\n"
        "- Cancelled: person cancels their own response (\"can't make it\")\n"
        "- Available: can respond if needed, no commitment yet\n"
        "- Informational: logistics/notes/questions\n"
        "- Unknown: unclear\n"
        "Vehicle normalization:\n"
        "- SAR units like 'sar78', 'SAR-078' => 'SAR-78'\n"
        "- Personal vehicle => 'POV'\n"
        "- Otherwise 'Unknown'\n"
        "ETA rules:\n"
        "- Absolute local times (e.g., 0945, 9:45 am) => convert to UTC for eta_iso on current date; if not future relative to current local, roll to next day.\n"
        "- Durations (e.g., 'in 20', '30 minutes', '1 hr') => add to CURRENT LOCAL time; convert result to UTC.\n"
        "- Ranges (e.g., '10:15-10:30') => choose the conservative upper bound.\n"
        "- If stand down or cancel => eta_iso='Unknown'.\n"
        "- If no new time and the person is still responding => it is acceptable to keep previous ETA.\n"
        "Examples (local->UTC conversion is REQUIRED):\n"
        "  Local 09:45 -> UTC 16:45Z if local is UTC-7.\n"
        "  'ETA 30 min' at local 14:20 -> UTC 21:50Z if UTC-7 (14:50 local).\n"
    )

    messages_payload: List[ChatCompletionMessageParam] = [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": user_msg},
    ]

    def _try_call(kwargs: Dict[str, Any], with_json_format: bool) -> Optional[str]:
        try:
            assert azure_openai_deployment is not None
            if with_json_format:
                resp = c.chat.completions.create(
                    model=azure_openai_deployment,
                    messages=messages_payload,
                    response_format={"type": "json_object"},
                    **kwargs
                )
            else:
                resp = c.chat.completions.create(
                    model=azure_openai_deployment,
                    messages=messages_payload,
                    **kwargs
                )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            etxt = str(e).lower()
            # prune unsupported knobs and retry upstream
            for k in ("temperature", "top_p", "presence_penalty", "frequency_penalty", "verbosity", "reasoning_effort"):
                if k in kwargs and (k.replace("_", " ") in etxt or "unknown" in etxt):
                    kwargs.pop(k, None)
            if "max tokens" in etxt or "output limit" in etxt or "too long" in etxt:
                kwargs["max_tomakens"] = min(2048, max(kwargs.get("max_completion_tokens", 768) * 2, 1024))
            return None

    kwargs = _select_kwargs_for_model(azure_openai_deployment)

    content = _try_call(dict(kwargs), with_json_format=True)
    if not content:
        content = _try_call(dict(kwargs), with_json_format=False)
    if not content or not content.strip():
        # last-ditch compact retry
        messages_retry: List[ChatCompletionMessageParam] = [
            {"role": "system", "content": "Return ONLY valid compact JSON per schema."},
            {"role": "user", "content": f"{user_msg}\nReturn only JSON."},
        ]
        try:
            resp = c.chat.completions.create(
                model=azure_openai_deployment,
                messages=messages_retry,
                response_format={"type": "json_object"},
                max_completion_tokens=min(2048, max(kwargs.get("max_completion_tokens", 768), 1024)),
            )
            content = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            logger.error(f"Final LLM retry failed: {e}")
            return {"_llm_error": str(e)}

    try:
        return json.loads(content) if content else {"_llm_error": "empty"}
    except Exception:
        m = re.search(r"\{.*\}", content or "", flags=re.S)
        if not m:
            return {"_llm_error": "non-json"}
        try:
            return json.loads(m.group(0))
        except Exception as e:
            return {"_llm_error": f"json-parse-failed: {e}"}


def _derive_eta_fields(text: str, llm_data: Dict[str, Any], base_dt: datetime, prev_eta_iso: Optional[str]) -> Tuple[Dict[str, Any], str]:
    source = "LLM"
    eta_iso = str(llm_data.get("eta_iso") or "Unknown")

    if eta_iso and eta_iso != "Unknown":
        try:
            dt = datetime.fromisoformat(eta_iso.replace("Z", "+00:00"))
            fields = compute_eta_fields(None, dt, base_dt)
        except Exception:
            fields = {"eta": "Unknown", "eta_timestamp": None, "eta_timestamp_utc": None, "minutes_until_arrival": None}
    else:
        fields = {"eta": "Unknown", "eta_timestamp": None, "eta_timestamp_utc": None, "minutes_until_arrival": None}

    if not fields.get("eta_timestamp_utc") and not fields.get("eta_timestamp"):
        # alt hh:mm keys
        for k in ("eta", "eta_hhmm", "eta_text"):
            v = llm_data.get(k)
            if isinstance(v, str) and re.fullmatch(r"\d{1,2}:\d{2}", v.strip()):
                fields = compute_eta_fields(v.strip(), None, base_dt)
                source = "Deterministic"
                break

    if not fields.get("eta_timestamp_utc") and not fields.get("eta_timestamp"):
        det = extract_eta_from_text_local(text, base_dt)
        if det:
            fields = compute_eta_fields(None, det, base_dt)
            source = "Deterministic"

    if not fields.get("eta_timestamp_utc") and not fields.get("eta_timestamp"):
        dur = extract_duration_eta(text, base_dt)
        if dur:
            fields = compute_eta_fields(None, dur, base_dt)
            source = "Deterministic"

    if not fields.get("eta_timestamp_utc") and not fields.get("eta_timestamp"):
        if prev_eta_iso and prev_eta_iso != "Unknown" and not _is_standdown(text):
            try:
                prev_dt = datetime.fromisoformat(prev_eta_iso.replace("Z", "+00:00"))
                fields = compute_eta_fields(None, prev_dt, base_dt)
                source = "Deterministic"
            except Exception:
                pass

    # override if model returned a past time but the text clearly specifies AM/PM
    try:
        mins = fields.get("minutes_until_arrival")
        if isinstance(mins, int) and mins <= -5 and re.search(r"(?i)\b(am|pm)\b", text or ""):
            det = extract_eta_from_text_local(text, base_dt)
            if det:
                fields = compute_eta_fields(None, det, base_dt)
                source = "Deterministic"
    except Exception:
        pass

    return fields, source


def extract_details_from_text(text: str, base_time: Optional[datetime] = None, prev_eta_iso: Optional[str] = None) -> Dict[str, Any]:
    anchor = base_time or now_tz()

    # Allow tests to inject main.client
    active_client = None
    try:
        import main as _main
        active_client = getattr(_main, "client", None)
    except ImportError:
        active_client = client

    llm_data = _call_llm_only(text, anchor, prev_eta_iso, active_client)

    # Enhanced debugging for LLM responses
    logger.info(f"LLM DEBUG - Input text: '{text}'")
    logger.info(f"LLM DEBUG - Raw response: {llm_data}")

    if isinstance(llm_data, dict) and (llm_data.get("_llm_unavailable") or llm_data.get("_llm_error")):
        logger.warning(f"LLM unavailable or error: {llm_data}")
        return {
            "vehicle": "Unknown",
            "eta": "Unknown",
            "raw_status": "Unknown",
            "arrival_status": "Unknown",
            "status_source": "LLM-Only",
            "status_confidence": 0.0,
            "eta_timestamp": None,
            "eta_timestamp_utc": None,
            "minutes_until_arrival": None,
            "parse_source": "LLM",
        }

    vehicle = _normalize_vehicle_name(str(llm_data.get("vehicle") or "Unknown"))
    status = str(llm_data.get("status") or "Unknown")
    try:
        confidence = float(llm_data.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0

    eta_fields, eta_source = _derive_eta_fields(text, llm_data, anchor, prev_eta_iso)

    if DEBUG_FULL_LLM_LOG:
        try:
            logger.info(f"LLM raw: {llm_data}")
        except Exception:
            pass

    return {
        "vehicle": vehicle,
        "eta": eta_fields.get("eta", "Unknown"),
        "raw_status": status,
        "arrival_status": status,  # webhook may flip to "Arrived" based on minutes
        "status_source": "LLM-Only",
        "status_confidence": confidence,
        "eta_timestamp": eta_fields.get("eta_timestamp"),
        "eta_timestamp_utc": eta_fields.get("eta_timestamp_utc"),
        "minutes_until_arrival": eta_fields.get("minutes_until_arrival"),
        "parse_source": eta_source,
    }
