import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple
from openai import AzureOpenAI, APIConnectionError, APIStatusError
import time
from openai.types.chat import ChatCompletionMessageParam

from .model_output import ModelExtraction

from .config import (
    azure_openai_api_key, azure_openai_endpoint, azure_openai_deployment,
    azure_openai_api_version, TIMEZONE, APP_TZ,
    DEFAULT_MAX_COMPLETION_TOKENS, MIN_COMPLETION_TOKENS, MAX_COMPLETION_TOKENS_CAP,
    LLM_REASONING_EFFORT, LLM_VERBOSITY, LLM_MAX_RETRIES, LLM_TOKEN_INCREASE_FACTOR,
    ENABLE_LLM_MOCK
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
            timeout=30.0,
            max_retries=0,
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
    - CRITICAL: The user's recent message history is provided showing their previous messages, statuses, and ETAs.
      Use this history to maintain consistency - especially preserving "Responding" status for follow-up messages.
    - Current time is provided in BOTH UTC and local time below.
    - Local timezone: {TIMEZONE}
    - IMPORTANT: Assume times mentioned in messages are LOCAL ({TIMEZONE}) unless explicitly marked otherwise. Convert local times to UTC for the final eta_iso.
    - IMPORTANT: If a user previously provided an ETA (like "11:00") and now says something like "switching to SAR 78", they are likely updating their vehicle while keeping the SAME ETA.
    - IMPORTANT: If the user says "same ETA" or gives an update without a new time and they remain Responding, KEEP their most recent ETA from history.
    - Vehicles are typically SAR-<number>, but users may use shorthand ("taking 108", "grabbing 75", "coming in 99").
    - Vehicle types to output: "POV", "SAR-<number>", "SAR Rig", or "Unknown".
    - If no vehicle is mentioned, use "Unknown". Do not infer a vehicle from response status.
    - NEVER use a status label (like "Not Responding") as a vehicle type.

    Status classification:
    - "Responding": actively responding / ETA updates while already responding.
      IMPORTANT: If the user's previous status was "Responding" and the current message doesn't explicitly cancel/standdown, 
      MAINTAIN "Responding" status even for follow-up questions or informational messages (e.g., "park at trailhead?", "bringing extra gear").
      Only change from "Responding" if there's clear evidence they're cancelling or standing down.
    - "Cancelled": the person cancels their own response ("can't make it", "backing out").
    - "Not Responding": acknowledges stand down / "10-22" / "1022" / mission canceled acknowledgements.
    - "Informational": logistics/questions/assignments (not a commitment to respond). 
      Only use this if they were NOT previously "Responding" or if they explicitly cancelled.
    - "Available": willing to respond if needed, not committed (no ETA).
    - "Unknown": unclear intent.

    Disambiguating "10-22"/"1022":
    - These normally mean stand down → "Not Responding".
    - HOWEVER, if clearly used as a TIME (e.g., preceded by "ETA" or in a clock-like context), interpret "1022" as 10:22 local, NOT stand down.

    Time parsing & ETA rules:
    - Parse ALL time formats: absolute times (0830, 8:30 am, 15:00), military/compact (2145), durations ("in 20", "15-20 minutes", "1 hr"), and relative phrases.
    - For ranges ("10:15-10:30"), choose the conservative upper bound (10:30).
    - CRITICAL: For ambiguous "ETA X:XX" formats, use CONTEXTUAL REASONING:
      * Consider BOTH interpretations: Duration (X hours XX minutes from now) vs Clock time (arriving at X:XX)
      * Apply OPERATIONAL COMMON SENSE: SAR responses typically 1-4 hours from alert, evening alerts usually get same-day responses
      * Very early AM arrivals (1-4 AM) are uncommon without explicit AM indicators
      * Example: "ETA 1:33" at 17:30 → Duration interpretation (19:03) is more reasonable than clock time (01:33 tomorrow)
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
        f"Note: Message history is included in the message text below when available.\n"
        f"Message: {text}\n"
        "Return ONLY the JSON."
    )

    return sys_msg, user_msg


def _call_mock_llm(text: str, base_dt: datetime) -> Dict[str, Any]:
    """
    Simulates an LLM response for local development/testing without Azure OpenAI.
    """
    text_lower = text.lower()
    
    # Default mock response
    mock_response = {
        "vehicle": "POV",
        "eta_iso": "Unknown",
        "status": "Unknown",
        "evidence": "mock_default",
        "confidence": 0.8
    }

    # Status detection
    if any(x in text_lower for x in ["stand down", "10-22", "cancel", "not responding"]):
        mock_response["status"] = "Not Responding"
        mock_response["vehicle"] = "Unknown"
    elif any(x in text_lower for x in ["eta", "en route", "responding", "omw", "coming", "headed"]):
        mock_response["status"] = "Responding"
    elif any(x in text_lower for x in ["available", "standing by"]):
        mock_response["status"] = "Available"
    
    # Vehicle detection
    sar_match = re.search(r"sar\s*[-]?\s*(\d+)", text_lower)
    if sar_match:
        mock_response["vehicle"] = f"SAR-{sar_match.group(1)}"
    elif "rig" in text_lower:
        mock_response["vehicle"] = "SAR Rig"

    # ETA Mocking (simple duration)
    # If we found "Responding" or similar, try to guess an ETA for the mock
    if mock_response["status"] == "Responding":
        # Look for "X min"
        min_match = re.search(r"(\d+)\s*min", text_lower)
        if min_match:
            try:
                mins = int(min_match.group(1))
                eta_dt = base_dt + timedelta(minutes=mins)
                mock_response["eta_iso"] = eta_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                mock_response["evidence"] = f"Mock parsed {mins} min"
            except Exception:
                pass
    
    return mock_response


def _call_llm_only(text: str, base_dt: datetime, prev_eta_iso: Optional[str], llm_client=None, debug: bool = False,
                   sys_prompt_override: Optional[str] = None, user_prompt_override: Optional[str] = None,
                   verbosity_override: Optional[str] = None, reasoning_effort_override: Optional[str] = None,
                   max_tokens_override: Optional[int] = None) -> Dict[str, Any]:
    if ENABLE_LLM_MOCK:
        logger.info("Processing message with mock LLM")
        return _call_mock_llm(text, base_dt)

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

    kwargs = _select_kwargs_for_model(azure_openai_deployment)
    if verbosity_override:
        value = str(verbosity_override).lower().strip()
        if value in ("low", "medium", "high"):
            kwargs["verbosity"] = value
    if reasoning_effort_override:
        value = str(reasoning_effort_override).lower().strip()
        if value in ("minimal", "low", "medium", "high"):
            kwargs["reasoning_effort"] = value
    if isinstance(max_tokens_override, int) and max_tokens_override > 0:
        kwargs["max_completion_tokens"] = max(
            int(MIN_COMPLETION_TOKENS), min(int(MAX_COMPLETION_TOKENS_CAP), max_tokens_override)
        )

    content = None
    max_attempts = max(1, min(10, int(LLM_MAX_RETRIES)))
    error = "empty_response"
    removable = {"temperature", "top_p", "presence_penalty", "frequency_penalty", "verbosity", "reasoning_effort"}
    for attempt in range(1, max_attempts + 1):
        try:
            response = c.chat.completions.create(
                model=azure_openai_deployment,
                messages=messages_payload,
                response_format={"type": "json_object"},
                **kwargs,
            )
            choice = response.choices[0]
            refusal = getattr(choice.message, "refusal", None)
            if choice.finish_reason == "content_filter" or (isinstance(refusal, str) and refusal):
                return {"_llm_error": "content_filtered"}
            content = (choice.message.content or "").strip()
            if choice.finish_reason != "length" and content:
                break
            error = "output_limit" if choice.finish_reason == "length" else "empty_response"
            content = None
            current = int(kwargs.get("max_completion_tokens", DEFAULT_MAX_COMPLETION_TOKENS))
            kwargs["max_completion_tokens"] = min(
                int(MAX_COMPLETION_TOKENS_CAP),
                max(int(current * LLM_TOKEN_INCREASE_FACTOR), int(MIN_COMPLETION_TOKENS), 1024),
            )
        except APIStatusError as exc:
            error = f"provider_status_{exc.status_code}"
            body = exc.body if isinstance(exc.body, dict) else {}
            details = body.get("error", body)
            if not isinstance(details, dict):
                details = {}
            parameter = details.get("param")
            # Change only a parameter that the provider explicitly rejects.
            if (exc.status_code == 400 and details.get("code") in ("unsupported_parameter", "unsupported_value")
                    and isinstance(parameter, str) and parameter in removable and parameter in kwargs):
                kwargs.pop(parameter)
                continue
            if exc.status_code not in (408, 409, 429) and exc.status_code < 500:
                return {"_llm_error": error}
            if attempt < max_attempts:
                time.sleep(min(2 ** (attempt - 1), 8))
        except APIConnectionError:
            error = "provider_connection_failed"
            if attempt < max_attempts:
                time.sleep(min(2 ** (attempt - 1), 8))
        except Exception:
            logger.error("LLM request failed")
            return {"_llm_error": "provider_request_failed"}
    if not content:
        logger.warning("LLM extraction failed after bounded attempts: %s", error)
        return {"_llm_error": error}

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


def _validated_model_output(value):
    if not isinstance(value, dict):
        return {"_llm_error": "invalid_model_output"}
    if value.get("_llm_error") or value.get("_llm_unavailable"):
        return value
    try:
        candidate = dict(value)
        if "vehicle" in candidate and isinstance(candidate["vehicle"], str):
            candidate["vehicle"] = _normalize_vehicle_name(candidate["vehicle"])
        validated = ModelExtraction.model_validate(candidate)
        return {**value, **validated.model_dump()}
    except Exception:
        logger.warning("Invalid structured model output")
        return {"_llm_error": "invalid_model_output"}


def _derive_eta_fields(text: str, llm_data: Dict[str, Any], base_dt: datetime, prev_eta_iso: Optional[str], status: str) -> Tuple[Dict[str, Any], str]:
    source = "LLM"

    # An explicit unknown ETA supersedes both model guesses and earlier ETAs.
    if re.search(r'\beta\s*(?:is\s*)?(?::\s*)?unknown[.!?\s]*$', text or '', re.IGNORECASE):
        return {
            "eta": "Unknown",
            "eta_timestamp": None,
            "eta_timestamp_utc": None,
            "minutes_until_arrival": None,
        }, "Rule"

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



def _validate_eta_against_context(eta_minutes: Optional[int], other_responders: Optional[List[Dict[str, Any]]] = None) -> bool:
    """
    Validate if an ETA makes sense given the context of other responders.
    Returns True if the ETA seems reasonable, False if anomalous.
    """
    if eta_minutes is None:
        return True  # Unknown ETA is always valid
    
    # Very negative ETAs (more than 2 hours in the past) are likely parsing errors
    if eta_minutes < -120:
        return False
    
    # Extremely far future ETAs (more than 24 hours) are likely parsing errors  
    if eta_minutes > 1440:
        return False
    
    if not other_responders:
        return True  # No context to compare against
    
    # Get ETAs from other responders for comparison
    other_etas = []
    for responder in other_responders:
        mins = responder.get("minutes_until_arrival")
        if isinstance(mins, int) and mins >= -30:  # Only consider reasonable ETAs
            other_etas.append(mins)
    
    if not other_etas:
        return True  # No other ETAs to compare against
    
    # Calculate statistics of other responders' ETAs
    other_etas.sort()
    median_eta = other_etas[len(other_etas) // 2]
    min_eta = min(other_etas)
    max_eta = max(other_etas)
    
    # If this ETA is way outside the range of other responders, it's suspicious
    eta_range = max_eta - min_eta
    if eta_range > 0:
        # If the new ETA is more than 3x the range away from the median, flag it
        distance_from_median = abs(eta_minutes - median_eta)
        if distance_from_median > max(180, eta_range * 3):  # At least 3 hours or 3x range
            return False
    
    return True


def _create_correction_prompt(text: str, parsed_eta: str, eta_minutes: Optional[int], 
                            other_responders: Optional[List[Dict[str, Any]]]) -> Tuple[str, str]:
    """
    Create a focused correction prompt for anomalous ETA parsing.
    """
    context_info = ""
    if other_responders:
        eta_list = []
        for r in other_responders:
            mins = r.get("minutes_until_arrival")
            eta_str = r.get("eta", "Unknown")
            if isinstance(mins, int) and mins >= -30 and eta_str != "Unknown":
                eta_list.append(f"{eta_str} ({mins} min)")
        
        if eta_list:
            context_info = f"\nOther responders' ETAs: {', '.join(eta_list[:5])}"  # Show up to 5
    
    sys_prompt = f"""
    You previously parsed an ETA that appears anomalous. Please re-evaluate this SAR response message.
    
    CRITICAL CONTEXT:
    - You parsed the ETA as: {parsed_eta} (which is {eta_minutes} minutes from now)
    - This seems unusual given the context{context_info}
    
    Common ETA parsing errors to avoid:
    1. Mistaking duration format "1:33" (1 hour 33 min) for clock time "1:33 AM"  
    2. UTC/timezone confusion causing next-day interpretations
    3. Interpreting relative times incorrectly
    
    Re-examine the message and provide a corrected interpretation. Focus on:
    - Is this a duration (X hours Y minutes from now) or a clock time?
    - Does the timing make operational sense for a SAR response?
    - Are there contextual clues about AM/PM or date?
    
    Return ONLY JSON:
    {{
    "vehicle": "POV" | "SAR-<number>" | "SAR Rig" | "Unknown",
    "eta_iso": "<UTC ISO like 2025-08-19T16:45:00Z or 'Unknown'>",  
    "status": "Responding" | "Cancelled" | "Available" | "Informational" | "Not Responding" | "Unknown",
    "evidence": "<phrase showing your reasoning>",
    "confidence": <float 0..1>,
    "correction_applied": true
    }}
    """
    
    user_prompt = f"Message to re-analyze: {text}\nProvide corrected JSON analysis."
    
    return sys_prompt, user_prompt


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
    other_responders: Optional[List[Dict[str, Any]]] = None,
    original_text: Optional[str] = None,
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

    # Only the current reply can trigger deterministic status and time rules.
    # History remains in the model prompt, separate from the source message.
    text = original_text if original_text is not None else text

    llm_data = _validated_model_output(llm_data)

    if isinstance(llm_data, dict) and (llm_data.get("_llm_unavailable") or llm_data.get("_llm_error")):
        logger.warning("LLM extraction unavailable or invalid")
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
            "parse_source": "Failed",
            "extraction_failed": True,
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

    evidence = str(llm_data.get("evidence") or "")

    # Check if ETA validation is needed and perform correction if anomalous
    eta_minutes = eta_fields.get("minutes_until_arrival")
    correction_applied = False
    
    if (eta_minutes is not None and 
        not _validate_eta_against_context(eta_minutes, other_responders) and
        status in ("Responding", "Available")):  # Only correct for response statuses
        
        logger.warning("ETA requires correction")

        try:
            # Create correction prompt with enhanced reasoning
            sys_correction, user_correction = _create_correction_prompt(
                text, eta_fields.get("eta", "Unknown"), eta_minutes, other_responders
            )
            
            # Call LLM again with high reasoning and correction context
            corrected_data = _call_llm_only(
                text, anchor, prev_eta_iso, active_client, debug=debug,
                sys_prompt_override=sys_correction,
                user_prompt_override=user_correction,
                verbosity_override="medium",  # Enhanced verbosity for correction
                reasoning_effort_override="high",  # Enhanced reasoning for correction
                max_tokens_override=1024
            )
            
            corrected_data = _validated_model_output(corrected_data)
            if (isinstance(corrected_data, dict) and 
                not corrected_data.get("_llm_unavailable") and 
                not corrected_data.get("_llm_error")):
                
                # Process corrected result
                corrected_eta_iso = str(corrected_data.get("eta_iso") or "Unknown")
                if corrected_eta_iso and corrected_eta_iso != "Unknown":
                    try:
                        corrected_dt = datetime.fromisoformat(corrected_eta_iso.replace("Z", "+00:00"))
                        corrected_fields = compute_eta_fields(None, corrected_dt, anchor)
                        corrected_minutes = corrected_fields.get("minutes_until_arrival")
                        
                        # Only apply correction if it's actually better
                        if _validate_eta_against_context(corrected_minutes, other_responders):
                            logger.info(f"ETA correction applied: {eta_fields.get('eta')} → {corrected_fields.get('eta')}")
                            eta_fields = corrected_fields
                            eta_source = "LLM-Corrected"
                            correction_applied = True
                            
                            # A time correction must not change independently extracted responder facts.
                            corrected_evidence = str(corrected_data.get("evidence") or "")
                            if corrected_evidence:
                                evidence = f"{evidence} [Corrected: {corrected_evidence}]"
                        else:
                            logger.warning("ETA correction resulted in another anomalous value, keeping original")
                    except Exception as e:
                        logger.warning(f"Failed to process corrected ETA: {e}")
                else:
                    logger.warning("Correction attempt returned Unknown ETA")
            else:
                logger.warning("ETA correction call failed")
                
        except Exception as e:
            logger.error(f"ETA correction attempt failed: {e}")

    result = {
        "vehicle": vehicle,
        "extraction_failed": False,
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
        "correction_applied": correction_applied,
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
