"""Utility functions for Respondr backend.

Contains datetime parsing, HTML escaping, display name normalization,
ETA computation, and other helper functions.
"""

import html
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import uuid

from .config import APP_TZ, is_testing, now_tz


def esc_html(v: Any) -> str:
    """Safe HTML escape helper."""
    try:
        return html.escape("" if v is None else str(v))
    except Exception:
        return ""


def normalize_display_name(raw_name: str) -> str:
    """Normalize display names by removing parenthetical content and excess whitespace."""
    try:
        name = raw_name or "Unknown"
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
        name = re.sub(r"\s{2,}", " ", name)
        return name if name else (raw_name or "Unknown")
    except Exception:
        return raw_name or "Unknown"


def parse_datetime_like(value: Any) -> Optional[datetime]:
    """Parse various datetime formats into timezone-aware datetime."""
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=APP_TZ)
        s = str(value)
        if "T" not in s and " " in s and ":" in s:
            s = s.replace(" ", "T")
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            try:
                dt = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
            except Exception:
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=APP_TZ)
        return dt.astimezone(APP_TZ)
    except Exception:
        return None


def coerce_datetime(s: Optional[str]) -> datetime:
    """Coerce various timestamp strings to a timezone-aware UTC datetime for stable sorting.
    Falls back to datetime.min UTC when parsing fails.
    """
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(s).replace('Z', '+00:00')).astimezone(timezone.utc)
    except Exception:
        try:
            # Legacy testing format: naive local time -> assume APP_TZ and convert to UTC
            dt_local = datetime.strptime(str(s), '%Y-%m-%d %H:%M:%S').replace(tzinfo=APP_TZ)
            return dt_local.astimezone(timezone.utc)
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)


def compute_eta_fields(eta_str: Optional[str], eta_ts: Optional[datetime], base_time: datetime) -> Dict[str, Any]:
    """Minimal ETA computation for admin edit endpoints.
    - If eta_ts provided: use directly.
    - Else if eta_str == HH:MM: apply to base_time date, roll to next day if <= base_time.
    - Else Unknown.
    """
    if eta_ts:
        eta_local = eta_ts.astimezone(APP_TZ)
        eta_dt_utc = eta_ts.astimezone(timezone.utc)
        minutes_until = int((eta_local - now_tz()).total_seconds() / 60)
        return {
            "eta": eta_local.strftime("%H:%M"),
            "eta_timestamp": (eta_local.strftime("%Y-%m-%d %H:%M:%S") if is_testing else eta_local.isoformat()),
            "eta_timestamp_utc": eta_dt_utc.isoformat(),
            "minutes_until_arrival": minutes_until,
            "arrival_status": ("Responding" if minutes_until > 0 else "Arrived"),
        }

    if isinstance(eta_str, str) and re.fullmatch(r"\d{1,2}:\d{2}", eta_str.strip() or ""):
        h, m = map(int, eta_str.strip().split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return {"eta": "Unknown", "eta_timestamp": None, "eta_timestamp_utc": None, "minutes_until_arrival": None, "arrival_status": "Unknown"}
        eta_local = base_time.replace(hour=h, minute=m, second=0, microsecond=0)
        if eta_local <= base_time:
            eta_local += timedelta(days=1)
        eta_dt_utc = eta_local.astimezone(timezone.utc)
        minutes_until = int((eta_local - now_tz()).total_seconds() / 60)
        return {
            "eta": eta_local.strftime("%H:%M"),
            "eta_timestamp": (eta_local.strftime("%Y-%m-%d %H:%M:%S") if is_testing else eta_local.isoformat()),
            "eta_timestamp_utc": eta_dt_utc.isoformat(),
            "minutes_until_arrival": minutes_until,
            "arrival_status": ("Responding" if minutes_until > 0 else "Arrived"),
        }

    return {
        "eta": "Unknown",
        "eta_timestamp": None,
        "eta_timestamp_utc": None,
        "minutes_until_arrival": None,
        "arrival_status": "Unknown",
    }


def extract_eta_from_text_local(text: str, base_time: datetime) -> Optional[datetime]:
    """Deterministically extract an ETA from explicit local-time mentions in text.
    Supports:
    - HH:MM AM/PM or H:MM am/pm or HH am/pm
    - 4-digit military times like 2145 (interpreted as local time)
    Returns a timezone-aware datetime in APP_TZ, rolled to next day if not in the future relative to base_time.
    """
    s = text or ""
    try:
        # 1) AM/PM formats
        m = re.search(r"(?i)\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", s)
        if m:
            h = int(m.group(1))
            mnt = int(m.group(2) or 0)
            ampm = m.group(3).lower()
            if not (1 <= h <= 12 and 0 <= mnt <= 59):
                return None
            if ampm == "pm" and h != 12:
                h += 12
            if ampm == "am" and h == 12:
                h = 0
            eta_local = base_time.replace(hour=h, minute=mnt, second=0, microsecond=0)
            if eta_local <= base_time:
                eta_local += timedelta(days=1)
            return eta_local

        # 2) Military 4-digit like 2145 or 0930
        m2 = re.search(r"\b((?:[01]\d|2[0-3])[0-5]\d)\b", s)
        if m2:
            val = m2.group(1)
            h = int(val[:2])
            mnt = int(val[2:])
            eta_local = base_time.replace(hour=h, minute=mnt, second=0, microsecond=0)
            if eta_local <= base_time:
                eta_local += timedelta(days=1)
            return eta_local
    except Exception:
        return None
    return None


def extract_duration_eta(text: str, base_time: datetime) -> Optional[datetime]:
    """Deterministically extract ETA from duration mentions like '15 min', '1 hr', '15-20 minutes'.
    Chooses a conservative upper bound when a range is provided (e.g., 15-20 → 20 minutes).
    Returns a timezone-aware datetime in APP_TZ; never returns a past time (adds to base_time).
    """
    s = (text or "").lower()
    try:
        # minutes range or single
        m = re.search(r"\b(\d{1,3})(?:\s*[-~]\s*(\d{1,3}))?\s*(?:min|mins|minute|minutes)\b", s)
        if m:
            a = int(m.group(1))
            b = int(m.group(2)) if m.group(2) else None
            minutes = max(a, b) if b is not None else a
            minutes = max(0, min(minutes, 24 * 60))  # clamp to one day
            return base_time + timedelta(minutes=minutes)

        # hours range or single
        h = re.search(r"\b(\d{1,2})(?:\s*[-~]\s*(\d{1,2}))?\s*(?:hr|hrs|hour|hours)\b", s)
        if h:
            a = int(h.group(1))
            b = int(h.group(2)) if h.group(2) else None
            hours = max(a, b) if b is not None else a
            hours = max(0, min(hours, 48))  # clamp to two days
            return base_time + timedelta(hours=hours)
    except Exception:
        return None
    return None

def convert_to_groupme_format(processed_messages):
    """
    Convert processed responder messages back to original GroupMe webhook schema format.
    
    Args:
        processed_messages: List of processed message dictionaries
        
    Returns:
        List of messages in GroupMe webhook format
    """
    groupme_messages = []
    
    for msg in processed_messages:
        # Convert timestamp to Unix timestamp (integer)
        created_at = None
        if msg.get('timestamp_utc'):
            dt = datetime.fromisoformat(msg['timestamp_utc'].replace('Z', '+00:00'))
            created_at = int(dt.timestamp())
        
        # Map processed message fields to GroupMe schema
        groupme_msg = {
            "attachments": [],  # Default empty array
            "avatar_url": None,  # Not available in processed data
            "created_at": created_at,
            "group_id": msg.get('group_id'),
            "id": msg.get('id'),
            "name": msg.get('name'),
            "sender_id": msg.get('user_id'),  # Map user_id to sender_id
            "sender_type": "user",  # Default to user type
            "source_guid": str(uuid.uuid4()),  # Generate new source_guid
            "system": False,  # Default to False
            "text": msg.get('text'),
            "user_id": msg.get('user_id')
        }
        
        groupme_messages.append(groupme_msg)
    
    return groupme_messages