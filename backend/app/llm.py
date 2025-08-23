import json
import logging
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from openai import AzureOpenAI
from openai.types.chat import ChatCompletionMessageParam

from .config import (
    azure_openai_api_key, azure_openai_endpoint, azure_openai_deployment,
    azure_openai_api_version, DEBUG_FULL_LLM_LOG, TIMEZONE, APP_TZ,
    DEFAULT_MAX_COMPLETION_TOKENS, MIN_COMPLETION_TOKENS, MAX_COMPLETION_TOKENS_CAP,
    LLM_REASONING_EFFORT, LLM_VERBOSITY
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

    # clamp weird LLM outputs like "SAR-1022"
    m = re.match(r"^\s*sar[\s-]?0*(\d{1,3})\s*$", s, re.I)
    if m:
        num = int(m.group(1))
        if 1 <= num <= MAX_SAR_UNIT:
            return f"SAR-{num}"
        return "Unknown"

    # If the model tried to bake the code into vehicle (e.g., "SAR-1022")
    if re.search(r"\b10\s*-?\s*22\b|\b1022\b", s.lower()):
        return "Unknown"

    if s.upper() in {"POV", "SAR RIG"}:
        return s.upper().replace("SAR RIG", "SAR Rig")

    return s if s else "Unknown"



MAX_SAR_UNIT = 199  # clamp plausible SAR unit range

def _has_eta_intent(text: str) -> bool:
    s = (text or "").lower()

    # very strong positive signals
    positive = [
        " eta", "eta ", "responding", "en route", "enroute", "on my way", "omw",
        "arriving", "be there", "be at", "headed to", "headed for", "coming in",
        "coming", "will arrive", "will be there", "will be at"
    ]
    if any(p in s for p in positive):
        return True

    # time range like "10:15-10:30" (upper-bound ETA pattern)
    if re.search(r"\b\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\b", s):
        return True

    # bare time often used with names (e.g., "Linda 10:15-10:30")
    # treat as ETA intent if message is mostly name + time and lacks negative cues
    if re.search(r"\b\d{1,2}:\d{2}\b", s) and not _has_non_eta_time_context(s):
        return True

    return False


def _has_non_eta_time_context(s: str) -> bool:
    s = s.lower()
    FOUR_DIGIT = r"(?:(?:[01]\d|2[0-3])[0-5]\d)"
    COLON_TIME = r"(?:(?:[01]?\d|2[0-3]):[0-5]\d)"

    # Any time token preceded by negative cues within 12 chars → not an ETA
    neg_cues = ["left", "last seen", "ls", "lkp", "departed", "reported", "call recvd", "call received"]

    for m in re.finditer(rf"\b({COLON_TIME}|{FOUR_DIGIT})\b", s):
        start = max(0, m.start() - 12)
        ctx = s[start:m.start()]
        if any(k in ctx for k in neg_cues):
            return True
    return False


def _looks_like_code_1022(text: str) -> bool:
    s = (text or "").lower()
    # 10-22 or 10 22 is STAND-DOWN code
    if re.search(r"\b10\s*-\s*22\b", s) or re.search(r"\b10\s+22\b", s):
        return True
    # bare 1022 is code UNLESS clearly in time context (eta, 'at', or has colon '10:22')
    if re.search(r"\b1022\b", s):
        if re.search(r"\beta[ :]\b|\bat\b|\barriv", s) or re.search(r"\b10:22\b", s):
            return False
        return True
    return False


def _contains_ics_role(text: str) -> bool:
    s = (text or "").lower()
    # light heuristic: common ICS/IMT words
    roles = [" ic ", " ic,", " ic.", " ops chief", " operations chief", "planning", "logistics", "pio", "safety", "icp "]
    # also handle "SAR6 IC" (IC at the end)
    if re.search(r"\b(ic|icp)\b", s):
        return True
    return any(r in s for r in roles)


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
    kw: Dict[str, Any] = {
        "max_completion_tokens": int(DEFAULT_MAX_COMPLETION_TOKENS or 768),
        "temperature": 1,
        "top_p": 1,
        "presence_penalty": 0,
        "frequency_penalty": 0,
    }
    
    # Use configured values from config.py as defaults
    kw["verbosity"] = LLM_VERBOSITY
    kw["reasoning_effort"] = LLM_REASONING_EFFORT
    
    # Model-specific overrides (if needed for specific models)
    if re.search(r"gpt-5-(nano|mini)", model_name or "", re.I):
        # For nano/mini models, use lower settings if not already low
        if LLM_VERBOSITY not in ("low",):
            kw["verbosity"] = "low"
        # NOTE: previously we forced a lower reasoning_effort for very small
        # models which caused `reasoning_effort` to drop to "low" even when
        # the operator configured a higher default (e.g., "medium"). That
        # behavior was surprising in preprod. Preserve the configured
        # `LLM_REASONING_EFFORT` here and only adjust verbosity for
        # resource-constrained models.
    
    return kw


def build_prompts(text: str, base_dt: datetime, prev_eta_iso: Optional[str]) -> Tuple[str, str]:
    """Build the system and user prompts for the LLM based on inputs.

    Returns (sys_prompt, user_prompt).
    """
    cur_utc = base_dt.astimezone(timezone.utc)
    cur_loc = base_dt.astimezone(APP_TZ)

    sys_msg = f"""
    You are analyzing Search & Rescue (SAR) response messages. Extract vehicle, ETA, and response status with full parsing and normalization.

    Context & assumptions:
    - Messages are from SAR responders coordinating by chat.
    - Typical pattern: whether they are responding, a vehicle type, and an ETA.
    - Consider the user's recent message history (provided in the input) to maintain consistency across updates.
    - Current time is provided in BOTH UTC and local time below.
    - Local timezone: {TIMEZONE}
    - IMPORTANT: Assume times mentioned in messages are LOCAL ({TIMEZONE}) unless explicitly marked otherwise. Convert local times to UTC for the final eta_iso.
    - IMPORTANT: If a user previously provided an ETA (like "11:00") and now says something like "switching to SAR 78", they are likely updating their vehicle while keeping the SAME ETA.
    - IMPORTANT: If the user says "same ETA" or gives an update without a new time and they remain Responding, KEEP their most recent ETA from history.
    - Vehicles are typically SAR-<number>, but users may use shorthand ("taking 108", "grabbing 75", "coming in 99").
    - Vehicle types to output: "POV", "SAR-<number>", "SAR Rig", or "Unknown".
    - If the person is clearly Responding but no vehicle is mentioned, default vehicle to "POV".
    - NEVER use a status label (like "Not Responding") as a vehicle type.

    Status classification:
    - "Responding": actively responding / ETA updates while already responding.
    - "Cancelled": the person cancels their own response ("can't make it", "backing out").
    - "Not Responding": acknowledges stand down / "10-22" / "1022" / mission canceled acknowledgements.
    - "Informational": logistics/questions/assignments (not a commitment to respond).
    - "Available": willing to respond if needed, not committed (no ETA).
    - "Unknown": unclear intent.

    Disambiguating "10-22"/"1022":
    - These normally mean stand down → "Not Responding".
    - HOWEVER, if clearly used as a TIME (e.g., preceded by "ETA" or in a clock-like context), interpret "1022" as 10:22 local, NOT stand down.

    Time parsing & ETA rules:
    - Parse ALL time formats: absolute times (0830, 8:30 am, 15:00), military/compact (2145), durations ("in 20", "15-20 minutes", "1 hr"), and relative phrases.
    - For ranges ("10:15-10:30"), choose the conservative upper bound (10:30).
    - Durations are relative to the CURRENT LOCAL time.
    - Convert the final ETA to ISO-8601 UTC in "eta_iso".
    - If stand down / cancel → eta_iso = "Unknown".
    - If no time and no prior ETA → eta_iso = "Unknown".

    Output JSON ONLY (no extra keys, no prose):
    {{
    "vehicle": "POV" | "SAR-<number>" | "SAR Rig" | "Unknown",
    "eta_iso": "<UTC ISO like 2025-08-19T16:45:00Z or 'Unknown'>",
    "status": "Responding" | "Cancelled" | "Available" | "Informational" | "Not Responding" | "Unknown",
    "evidence": "<very short phrase from the message>",
    "confidence": <float 0..1>
    }}

    Local→UTC examples (assume UTC-7):
    - Local 09:45 → 16:45Z
    - Local 'ETA 30 min' at 14:20 → local 14:50 → 21:50Z
    - 'ETA 1022' with "ETA" present → 10:22 local → 17:22Z
    """

    user_msg = (
        f"Current time (UTC): {cur_utc.isoformat().replace('+00:00','Z')}\n"
        f"Current time (Local {TIMEZONE}): {cur_loc.isoformat()}\n"
        f"Previous ETA (UTC, optional): {prev_eta_iso or 'None'}\n"
        f"(History snapshot may be appended in the message body if available.)\n"
        f"Message: {text}\n"
        "Return ONLY the JSON."
    )

    return sys_msg, user_msg


def _call_llm_only(text: str, base_dt: datetime, prev_eta_iso: Optional[str], llm_client=None, debug: bool = False,
                   sys_prompt_override: Optional[str] = None, user_prompt_override: Optional[str] = None,
                   verbosity_override: Optional[str] = None, reasoning_effort_override: Optional[str] = None,
                   max_tokens_override: Optional[int] = None) -> Dict[str, Any]:
    c = llm_client or client
    if not c:
        return {"_llm_unavailable": True}
    if not azure_openai_deployment:
        return {"_llm_error": "No deployment configured"}
    assert azure_openai_deployment is not None

    if sys_prompt_override is not None or user_prompt_override is not None:
        # Use overrides, falling back to built defaults for any missing part
        _sys, _user = build_prompts(text, base_dt, prev_eta_iso)
        sys_msg = sys_prompt_override if sys_prompt_override is not None else _sys
        user_msg = user_prompt_override if user_prompt_override is not None else _user
    else:
        sys_msg, user_msg = build_prompts(text, base_dt, prev_eta_iso)


    messages_payload: List[ChatCompletionMessageParam] = [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": user_msg},
    ]
    debug_info: Dict[str, Any] = {}
    if debug:
        debug_info["sys_prompt"] = sys_msg
        debug_info["user_prompt"] = user_msg

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
                current = int(kwargs.get("max_completion_tokens", DEFAULT_MAX_COMPLETION_TOKENS))
                # Increase but clamp to cap; ensure at least a floor (e.g., 1024) when escalating
                kwargs["max_completion_tokens"] = min(
                    int(MAX_COMPLETION_TOKENS_CAP),
                    max(current * 2, max(int(MIN_COMPLETION_TOKENS), 1024))
                )
            return None

    kwargs = _select_kwargs_for_model(azure_openai_deployment)
    # Log the resolved LLM kwargs so operators can verify what will be sent
    try:
        logger.debug(f"LLM kwargs before overrides: {kwargs}")
    except Exception:
        pass
    # Apply optional overrides if provided and valid
    if verbosity_override:
        v = str(verbosity_override).lower().strip()
        if v in ("low", "medium", "high"):
            kwargs["verbosity"] = v
    if reasoning_effort_override:
        r = str(reasoning_effort_override).lower().strip()
        if r in ("minimal", "low", "medium", "high"):
            kwargs["reasoning_effort"] = r
    if isinstance(max_tokens_override, int) and max_tokens_override > 0:
        # Clamp to configured safe range; align with existing retry cap
        kwargs["max_completion_tokens"] = max(
            int(MIN_COMPLETION_TOKENS),
            min(int(MAX_COMPLETION_TOKENS_CAP), int(max_tokens_override))
        )

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
                max_completion_tokens=min(
                    int(MAX_COMPLETION_TOKENS_CAP),
                    max(int(kwargs.get("max_completion_tokens", DEFAULT_MAX_COMPLETION_TOKENS)), max(int(MIN_COMPLETION_TOKENS), 1024))
                ),
            )
            content = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            logger.error(f"Final LLM retry failed: {e}")
            return {"_llm_error": str(e)}

    try:
        parsed = json.loads(content) if content else {"_llm_error": "empty"}
        if debug and isinstance(parsed, dict):
            # Attach flattened debug fields as strings for easier consumption
            parsed["_debug_sys_prompt"] = debug_info.get("sys_prompt", "")
            parsed["_debug_user_prompt"] = debug_info.get("user_prompt", "")
            parsed["_debug_raw_response"] = content
        return parsed
    except Exception:
        m = re.search(r"\{.*\}", content or "", flags=re.S)
        if not m:
            res = {"_llm_error": "non-json"}
            if debug:
                res["_debug_sys_prompt"] = debug_info.get("sys_prompt", "")
                res["_debug_user_prompt"] = debug_info.get("user_prompt", "")
                res["_debug_raw_response"] = content
            return res
        try:
            parsed = json.loads(m.group(0))
            if debug and isinstance(parsed, dict):
                parsed["_debug_sys_prompt"] = debug_info.get("sys_prompt", "")
                parsed["_debug_user_prompt"] = debug_info.get("user_prompt", "")
                parsed["_debug_raw_response"] = content
            return parsed
        except Exception as e:
            res = {"_llm_error": f"json-parse-failed: {e}"}
            if debug:
                res["_debug_sys_prompt"] = debug_info.get("sys_prompt", "")
                res["_debug_user_prompt"] = debug_info.get("user_prompt", "")
                res["_debug_raw_response"] = content
            return res


def _derive_eta_fields(text: str, llm_data: Dict[str, Any], base_dt: datetime, prev_eta_iso: Optional[str], status: str) -> Tuple[Dict[str, Any], str]:
    source = "LLM"

    # If stand-down/cancel, never keep/parse ETA
    if _looks_like_code_1022(text) or _is_standdown(text):
        return {
            "eta": "Unknown",
            "eta_timestamp": None,
            "eta_timestamp_utc": None,
            "minutes_until_arrival": None
        }, "Rule"

    eta_iso = str(llm_data.get("eta_iso") or "Unknown")
    if eta_iso and eta_iso != "Unknown":
        try:
            dt = datetime.fromisoformat(eta_iso.replace("Z", "+00:00"))
            fields = compute_eta_fields(None, dt, base_dt)
        except Exception:
            fields = {"eta": "Unknown", "eta_timestamp": None, "eta_timestamp_utc": None, "minutes_until_arrival": None}
    else:
        fields = {"eta": "Unknown", "eta_timestamp": None, "eta_timestamp_utc": None, "minutes_until_arrival": None}

    # only run deterministic parsing if ETA intent (or model says Responding)
    eta_intent = _has_eta_intent(text) or status == "Responding"

    if not fields.get("eta_timestamp_utc") and not fields.get("eta_timestamp") and eta_intent and not _has_non_eta_time_context((text or "").lower()):
        # alt hh:mm keys
        for k in ("eta", "eta_hhmm", "eta_text"):
            v = llm_data.get(k)
            if isinstance(v, str) and re.fullmatch(r"\d{1,2}:\d{2}", v.strip()):
                fields = compute_eta_fields(v.strip(), None, base_dt)
                source = "Deterministic"
                break

    if not fields.get("eta_timestamp_utc") and not fields.get("eta_timestamp") and eta_intent and not _has_non_eta_time_context((text or "").lower()):
        det = extract_eta_from_text_local(text, base_dt)
        if det:
            fields = compute_eta_fields(None, det, base_dt)
            source = "Deterministic"

    if not fields.get("eta_timestamp_utc") and not fields.get("eta_timestamp") and eta_intent:
        dur = extract_duration_eta(text, base_dt)
        if dur:
            fields = compute_eta_fields(None, dur, base_dt)
            source = "Deterministic"

    if not fields.get("eta_timestamp_utc") and not fields.get("eta_timestamp"):
        # maintain previous ETA if still responding and not standdown
        if prev_eta_iso and prev_eta_iso != "Unknown" and status == "Responding":
            try:
                prev_dt = datetime.fromisoformat(prev_eta_iso.replace("Z", "+00:00"))
                fields = compute_eta_fields(None, prev_dt, base_dt)
                source = "Deterministic"
            except Exception:
                pass

    # override if model produced past ETA but text contains explicit AM/PM (likely mis-read)
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



def extract_details_from_text(
    text: str,
    base_time: Optional[datetime] = None,
    prev_eta_iso: Optional[str] = None,
    debug: bool = False,
    sys_prompt_override: Optional[str] = None,
    user_prompt_override: Optional[str] = None,
    verbosity_override: Optional[str] = None,
    reasoning_effort_override: Optional[str] = None,
    max_tokens_override: Optional[int] = None,
) -> Dict[str, Any]:
    anchor = base_time or now_tz()

    # Allow tests to inject main.client
    active_client = None
    try:
        import main as _main
        active_client = getattr(_main, "client", None)
    except ImportError:
        active_client = client

    llm_data = _call_llm_only(
        text,
        anchor,
        prev_eta_iso,
        active_client,
        debug=debug,
        sys_prompt_override=sys_prompt_override,
        user_prompt_override=user_prompt_override,
    verbosity_override=verbosity_override,
    reasoning_effort_override=reasoning_effort_override,
    max_tokens_override=max_tokens_override,
    )

    # Enhanced debugging for LLM responses
    logger.debug(f"LLM DEBUG - Input text: '{text}'")
    logger.debug(f"LLM DEBUG - Raw response: {llm_data}")

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
    orig_status = str(llm_data.get("status") or "Unknown").strip()
    status = orig_status
    status_source = "LLM"
    rules_applied: List[str] = []
    
    try:
        confidence = float(llm_data.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0

    # Force status to Not Responding on stand-down code phrases
    if _looks_like_code_1022(text) or _is_standdown(text):
        status = "Not Responding"
        rules_applied.append("standdown")
        vehicle = "Unknown"  # prevent POV/SAR-* in stand-down acks

    # ICS role heuristic: treat as Informational if no ETA intent
    if _contains_ics_role(text) and not _has_eta_intent(text):
        status = "Informational"
        rules_applied.append("ics")
        if vehicle.startswith("SAR-"):
            vehicle = "Unknown"

    if status != orig_status and rules_applied:
        status_source = "Rule"

    eta_fields, eta_source = _derive_eta_fields(text, llm_data, anchor, prev_eta_iso, status)

    # If Not Responding/Cancelled, ensure ETA is cleared regardless of LLM
    if status in ("Not Responding", "Cancelled"):
        eta_fields = {
            "eta": "Unknown",
            "eta_timestamp": None,
            "eta_timestamp_utc": None,
            "minutes_until_arrival": None
        }
        eta_source = "Rule"

    if DEBUG_FULL_LLM_LOG:
        try:
            logger.debug(f"LLM raw: {llm_data}")
        except Exception:
            pass

    evidence = str(llm_data.get("evidence") or "")

    result = {
        "vehicle": vehicle,
        "eta": eta_fields.get("eta", "Unknown"),
        "raw_status": status,
        "arrival_status": status,  # webhook may flip to "Arrived" based on minutes
        "status_source": status_source,
        "status_confidence": confidence,
        "eta_timestamp": eta_fields.get("eta_timestamp"),
        "eta_timestamp_utc": eta_fields.get("eta_timestamp_utc"),
        "minutes_until_arrival": eta_fields.get("minutes_until_arrival"),
        "parse_source": eta_source,
        "parse_evidence": evidence,
        # "rules_applied": rules_applied,  # optional, very helpful in /api/parse-debug
    }
    # Attach LLM debug info on request (flattened)
    if debug and isinstance(llm_data, dict):
        llm_debug = {
            "sys_prompt": str(llm_data.get("_debug_sys_prompt", "")),
            "user_prompt": str(llm_data.get("_debug_user_prompt", "")),
            "raw_response": str(llm_data.get("_debug_raw_response", "")),
        }
        result["llm_debug"] = llm_debug
        # Optionally include the raw llm_data sans large fields
        safe_raw = dict(llm_data)
        for k in ["_debug_sys_prompt", "_debug_user_prompt", "_debug_raw_response"]:
            if k in safe_raw:
                safe_raw.pop(k, None)
        result["llm_raw"] = safe_raw
    return result
