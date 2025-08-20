<<<<<<< HEAD
"""LLM processing for SAR message parsing."""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from openai import AzureOpenAI
from openai.types.chat import ChatCompletionMessageParam

from .config import (
    azure_openai_api_key, azure_openai_endpoint, azure_openai_deployment,
    azure_openai_api_version, DEBUG_FULL_LLM_LOG, disable_api_key_check
)
from .utils import extract_eta_from_text_local, extract_duration_eta, compute_eta_fields

logger = logging.getLogger(__name__)

# Initialize Azure OpenAI client
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


def extract_details_from_text(text: str, base_time: Optional[datetime] = None, prev_eta_iso: Optional[str] = None) -> Dict[str, Any]:
    """Extract vehicle, ETA, and status details from text using LLM.
    
    Args:
        text: The message text to parse
        base_time: Base time for ETA calculations (defaults to now)
        prev_eta_iso: Previous ETA in ISO format for maintaining state
        
    Returns:
        Dict with vehicle, eta, status, timestamps, and confidence info
    """
    if not base_time:
        base_time = datetime.now(timezone.utc)
    
    # Check for test client override in main module
    test_client = None
    try:
        import main
        test_client = getattr(main, 'client', None)
    except ImportError:
        pass
    
    active_client = test_client if test_client else client
    
    if not active_client:
        # Fallback when LLM is unavailable
        return {
            "vehicle": "Unknown",
            "eta": "Unknown",
            "raw_status": "Unknown",
            "arrival_status": "Unknown",  # Add this for webhook compatibility
            "status_source": "LLM-Only",
            "status_confidence": 0.0,
            "eta_timestamp": None,
            "eta_timestamp_utc": None,
            "minutes_until_arrival": None,
            "parse_source": "LLM",
        }
    
    try:
        # Call the LLM
        llm_data = _call_llm_only(text, base_time.isoformat(), prev_eta_iso, active_client)
        
        # Process LLM response
        vehicle_raw = str(llm_data.get("vehicle", "Unknown"))
        
        # Normalize vehicle names
        vehicle = _normalize_vehicle_name(vehicle_raw)
        
        # Get status and confidence
        status = str(llm_data.get("status", "Unknown"))
        confidence = float(llm_data.get("confidence", 0.0))
        
        # Process ETA - for LLM-only mode, no fallback parsing
        eta_iso = llm_data.get("eta_iso", "Unknown")
        if eta_iso and eta_iso != "Unknown":
            try:
                eta_dt = datetime.fromisoformat(eta_iso.replace('Z', '+00:00'))
                eta_fields = compute_eta_fields(None, eta_dt, base_time)
            except Exception:
                logger.warning(f"Invalid ETA ISO format from LLM: {eta_iso}")
                eta_fields = {
                    "eta": "Unknown",
                    "eta_timestamp": None,
                    "eta_timestamp_utc": None,
                    "minutes_until_arrival": None
                }
        else:
            eta_fields = {
                "eta": "Unknown", 
                "eta_timestamp": None,
                "eta_timestamp_utc": None,
                "minutes_until_arrival": None
            }
        
        return {
            "vehicle": vehicle,
            "eta": eta_fields.get("eta", "Unknown"),
            "raw_status": status,
            "arrival_status": status,  # Add this for webhook compatibility
            "status_source": "LLM-Only",
            "status_confidence": confidence,
            "eta_timestamp": eta_fields.get("eta_timestamp"),
            "eta_timestamp_utc": eta_fields.get("eta_timestamp_utc"),
            "minutes_until_arrival": eta_fields.get("minutes_until_arrival"),
            "parse_source": "LLM",
        }
        
    except Exception as e:
        logger.error(f"LLM extraction failed: {e}")
        return {
            "vehicle": "Unknown",
            "eta": "Unknown",
            "raw_status": "Unknown",
            "arrival_status": "Unknown",  # Add this for webhook compatibility
            "status_source": "LLM-Only",
            "status_confidence": 0.0,
            "eta_timestamp": None,
            "eta_timestamp_utc": None,
            "minutes_until_arrival": None,
            "parse_source": "LLM",
        }


def _call_llm_only(text: str, current_iso_utc: str, prev_eta_iso: Optional[str] = None, llm_client = None) -> Dict[str, Any]:
    """Call the LLM with SAR-specific prompt."""
    
    active_client = llm_client if llm_client else client
    
    if not active_client:
        return {"_llm_unavailable": True}
    
    if not azure_openai_deployment:
        return {"_llm_error": "No deployment configured"}
    
    # Parse current time to get human-readable format for context
    try:
        current_dt = datetime.fromisoformat(current_iso_utc.replace('Z', '+00:00'))
        current_time_str = current_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        current_time_short = current_dt.strftime("%H:%M")
    except Exception:
        current_time_str = current_iso_utc
        current_time_short = "Unknown"
    
    # Comprehensive SAR message parsing prompt with detailed examples
    prompt = f"""You are a SAR (Search and Rescue) message parser. Parse the message and return ONLY valid JSON.
Current time: {current_time_str} (24-hour format: {current_time_short})
Previous ETA: {prev_eta_iso or "None"}

Return JSON with fields: vehicle, eta_iso, status, confidence

STATUS DETECTION:
- 'Responding': Actively responding with intention to arrive
  Examples: 'Responding POV ETA 08:45', 'POV ETA 0830', 'Headed to Taylor's Landing'
  IMPORTANT: ETA updates from already responding people stay 'Responding'
  'Actually I'll be an hour and 10 min', 'Updated ETA 15:30', 'Make that 20 minutes'
- 'Cancelled': Mission cancelled or person can't respond
  Examples: 'can't make it', 'backing out', '10-22', 'Mission canceled', 'Subject found'
- 'Available': Can respond but no firm commitment (initial offer only)
  Examples: 'I can respond as IMT', 'I can help with planning'
  NOTE: If someone already responded, ETA updates are 'Responding', not 'Available'
- 'Informational': Providing information, logistics, questions
  Examples: 'Key for 74 is in key box', 'Who can respond?', 'checking with Hayden'
- 'Unknown': Cannot determine clear status

CANCELLATION DETECTION - Return status 'Cancelled':
- Examples of declining/negative responses:
  'can't make it', 'cannot make it', 'won't make it', 'not coming', 'backing out'
  'Ok I can't make it', 'I also can't make it', 'Sorry, backing out'
- Special codes: '10-22' (or '1022') means mission complete/cancelled
  'Copied 10-22', 'Copy 10-22', '10-22', '1022 subj found'
- Mission status: 'Mission canceled', 'Mission cancelled', 'Subject found'
- Logistics/info only: 'Key for 74 is in key box', 'Who can respond?'

VEHICLE EXTRACTION:
- SAR units: 'SAR-12', 'SAR 12', 'sar78', 'SAR-60' → format as 'SAR-XX'
- Personal vehicle: 'POV', 'personal vehicle', 'own car' → 'POV'
- Unknown/unclear → 'Unknown'
Examples:
  'SAR-3 on the way' → 'SAR-3'
  'Responding sar78' → 'SAR-78'
  'Driving POV' → 'POV'
  'I can respond as IMT' → 'Unknown'

ETA EXTRACTION (eta_iso field):
- Absolute times: Convert to ISO 8601 UTC timestamp
  '0830' → calculate from current date, return as ISO
  '1150' → calculate from current date, return as ISO
  '15:00' → calculate from current date, return as ISO
- Relative times: Calculate based on current time
  * '15 minutes', '15min', '15 mins' → add 15 minutes to current time
  * '30min', '30 minutes' → add 30 minutes to current time
  * '45 minutes', '45min' → add 45 minutes to current time
  * '60min', '60 minutes', '1 hour' → add 60 minutes to current time
  * '90min', '90 minutes' → add 90 minutes to current time
  * 'hour and 10 min', 'hour and 10 minutes' → add 70 minutes to current time
  * 'hour and a half', '1.5 hours' → add 90 minutes to current time
  * '2 hours', '120 minutes' → add 120 minutes to current time
  * 'in 20', 'be there in 20' → add 20 minutes to current time
- Unknown/unclear → 'Unknown'
- If cancelled status → 'Unknown'

Current time {current_time_short}: 'ETA 15 minutes' → add 15 minutes and convert to ISO
- No time mentioned → 'Unknown'
- DON'T interpret 'Xmin' as 'X:00' - calculate relative time!

Examples:
  Current time 14:20, 'ETA 15:00' → '2024-01-01T15:00:00Z' (use current date)
  Current time 14:20, '30 min out' → '2024-01-01T14:50:00Z' (add 30 min)
  Current time 12:07, 'ETA 60min' → '2024-01-01T13:07:00Z' (NOT '01:00'!)
  'POV ETA 0830' → '2024-01-01T08:30:00Z'
  'Updated eta: arriving 11:30' → '2024-01-01T11:30:00Z'

CONFIDENCE SCORING (0.0-1.0):
- 0.9-1.0: Clear, unambiguous vehicle and ETA
- 0.7-0.8: Clear intent, some ambiguity in details
- 0.5-0.6: Moderate confidence, some interpretation required
- 0.3-0.4: Low confidence, high ambiguity
- 0.0-0.2: Very unclear or contradictory

COMPLETE EXAMPLES:
  'Responding POV ETA 08:45' → {{"vehicle": "POV", "eta_iso": "2024-01-01T08:45:00Z", "status": "Responding", "confidence": 0.9}}
  'can't make it, sorry' → {{"vehicle": "Unknown", "eta_iso": "Unknown", "status": "Cancelled", "confidence": 0.8}}
  'I can respond as IMT' → {{"vehicle": "Unknown", "eta_iso": "Unknown", "status": "Available", "confidence": 0.7}}
  'Key for 74 is in key box' → {{"vehicle": "Unknown", "eta_iso": "Unknown", "status": "Informational", "confidence": 0.9}}
  '10-22' → {{"vehicle": "Unknown", "eta_iso": "Unknown", "status": "Cancelled", "confidence": 0.9}}
  'Mission canceled. Subject found' → {{"vehicle": "Unknown", "eta_iso": "Unknown", "status": "Cancelled", "confidence": 1.0}}
  'Who can respond to Vesper?' → {{"vehicle": "Unknown", "eta_iso": "Unknown", "status": "Informational", "confidence": 0.9}}
  'SAR-5 ETA 15:45' → {{"vehicle": "SAR-5", "eta_iso": "2024-01-01T15:45:00Z", "status": "Responding", "confidence": 0.9}}
  'Responding sar78 1150' → {{"vehicle": "SAR-78", "eta_iso": "2024-01-01T11:50:00Z", "status": "Responding", "confidence": 0.9}}
  'Responding SAR7 ETA 60min' → {{"vehicle": "SAR-7", "eta_iso": "2024-01-01T13:07:00Z", "status": "Responding", "confidence": 0.8}} (if current time is 12:07)
  'SAR-3 ETA 30min' → {{"vehicle": "SAR-3", "eta_iso": "2024-01-01T14:50:00Z", "status": "Responding", "confidence": 0.8}} (if current time is 14:20)
  'ETA 45 minutes' → {{"vehicle": "Unknown", "eta_iso": "2024-01-01T15:05:00Z", "status": "Responding", "confidence": 0.7}} (if current time is 14:20)
  'POV ETA 90min' → {{"vehicle": "POV", "eta_iso": "2024-01-01T15:50:00Z", "status": "Responding", "confidence": 0.8}} (if current time is 14:20)
  'Actually I'll be an hour and 10 min' (if already responding) → {{"vehicle": "Unknown", "eta_iso": "2024-01-01T15:30:00Z", "status": "Responding", "confidence": 0.7}} (if current time is 14:20)
  'Updated ETA 20 minutes' (if already responding) → {{"vehicle": "Unknown", "eta_iso": "2024-01-01T14:40:00Z", "status": "Responding", "confidence": 0.8}} (if current time is 14:20)
  'Make that 30 min' (if already responding) → {{"vehicle": "Unknown", "eta_iso": "2024-01-01T14:50:00Z", "status": "Responding", "confidence": 0.7}} (if current time is 14:20)

MESSAGE: "{text}"

Return ONLY this JSON format:
{{"vehicle": "value", "eta_iso": "ISO_timestamp_or_Unknown", "status": "value", "confidence": 0.X}}"""

    try:
        response = active_client.chat.completions.create(
            model=azure_openai_deployment,
            messages=[
                {"role": "system", "content": "You are a SAR message parser. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=4096
        )
        
        content = response.choices[0].message.content
        if not content:
            return {"_llm_error": "Empty response"}
            
        return json.loads(content.strip())
        
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return {"_llm_error": str(e)}


def _normalize_vehicle_name(vehicle_raw: str) -> str:
    """Normalize vehicle names to standard format."""
    vehicle_clean = vehicle_raw.strip()
    
    # Match SAR vehicles like "SAR78", "sar-078" -> "SAR-78"
    m = re.match(r"^\s*sar[\s-]?0*(\d{1,3})\s*$", vehicle_clean, re.I)
    if m:
        return f"SAR-{int(m.group(1))}"
    
    # Handle special cases
    if vehicle_clean.upper() in {"POV", "SAR RIG"}:
        return vehicle_clean.upper().replace("SAR RIG", "SAR Rig")
    
    return vehicle_clean if vehicle_clean else "Unknown"


def _process_eta(eta_iso: str, text: str, base_time: datetime, prev_eta_iso: Optional[str]) -> Dict[str, Any]:
    """Process ETA information with fallbacks."""
    
    # If LLM provided valid ETA
    if eta_iso and eta_iso != "Unknown":
        try:
            eta_dt = datetime.fromisoformat(eta_iso.replace('Z', '+00:00'))
            return compute_eta_fields(None, eta_dt, base_time)
        except Exception:
            logger.warning(f"Invalid ETA ISO format: {eta_iso}")
    
    # Try deterministic parsing for explicit times
    det_eta = extract_eta_from_text_local(text, base_time)
    if det_eta:
        return compute_eta_fields(None, det_eta, base_time)
    
    # Try duration-based parsing
    dur_eta = extract_duration_eta(text, base_time)
    if dur_eta:
        return compute_eta_fields(None, dur_eta, base_time)
    
    # Check for stand-down messages
    standdown_phrases = ["standing down", "stand down", "10-22", "1022", 
                        "can't make it", "cancelling", "cancelled", "not responding"]
    is_standdown = any(phrase in text.lower() for phrase in standdown_phrases)
    
    # Maintain previous ETA if not standing down
    if prev_eta_iso and prev_eta_iso != "Unknown" and not is_standdown:
        try:
            prev_dt = datetime.fromisoformat(prev_eta_iso.replace('Z', '+00:00'))
            return compute_eta_fields(None, prev_dt, base_time)
        except Exception:
            pass
    
    # Default to unknown
    return {
        "eta": "Unknown",
        "eta_timestamp": None,
        "eta_timestamp_utc": None,
        "minutes_until_arrival": None
    }
=======
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
>>>>>>> ef84adee5db2588b7c1441dfc10679fb2b09f3e0
