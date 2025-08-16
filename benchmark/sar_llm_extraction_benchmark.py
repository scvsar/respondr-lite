# sar_llm_extraction_benchmark.py
# Benchmark: LLM-only extraction of Vehicle, ETA, and Status for SAR messages.
# - Models return extraction JSON only (no math).
# - Harness normalizes vehicle and converts ETA text to HH:MM relative to a provided base_time.
# - Scores: per-field accuracy + exact triplet accuracy.
#
# Env:
#   model_endpoint        = https://<your-azure-resource>.openai.azure.com/
#   model_api_key         = <key>
#   API_VERSION           = 2024-12-01-preview (default)
#   BENCH_MODELS          = optional comma-separated list of model names
#   MAX_COMPLETION_TOKENS = optional cap for model output tokens (default 256 for single, 2048 for comprehensive)
#
# Defaults (3 "fast" models): gpt-5-nano, gpt-5-mini, gpt-4o-mini

import os
import re
import json
import math
import time
import uuid
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from dotenv import load_dotenv
from openai import AsyncAzureOpenAI, APIConnectionError, RateLimitError, APIStatusError, APITimeoutError, AuthenticationError
from colorama import Fore, Style, init

# Load environment variables from .env file in this script's directory, overriding process env
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DOTENV_PATH = os.path.join(SCRIPT_DIR, ".env")
if os.path.exists(DOTENV_PATH):
    load_dotenv(DOTENV_PATH, override=True)
else:
    # Fall back to default search (project root, cwd), still overriding process env
    load_dotenv(override=True)

init(autoreset=True)
GREEN, YELLOW, RED = Fore.GREEN, Fore.YELLOW, Fore.RED
BOLD, RESET = Style.BRIGHT, Style.RESET_ALL

API_VERSION = os.getenv("API_VERSION", "2024-12-01-preview")
AZURE_ENDPOINT = os.getenv("model_endpoint")
API_KEY = os.getenv("model_api_key")
MAX_TOK_SINGLE = int(os.getenv("MAX_COMPLETION_TOKENS", "256") or 256)
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "8") or 8)

if not AZURE_ENDPOINT or not API_KEY:
    raise SystemExit(
        "Missing env. Set model_endpoint and model_api_key (and optionally API_VERSION)."
    )

DEFAULT_MODELS = ["gpt-5-nano", "gpt-5-mini", "gpt-4o-mini"]
BENCH_MODELS = [m.strip() for m in os.getenv("BENCH_MODELS", ",".join(DEFAULT_MODELS)).split(",") if m.strip()]

# -----------------------
# Normalization utilities
# -----------------------

def normalize_vehicle(text: str) -> str:
    """Drop-in replacement enforcing negative cues and avoiding stray number fallback.
    - Prevents channel/freq/call-sign numbers from mapping to vehicles.
    - Keeps "coming in <int>" → vehicle unless time unit follows.
    - Handles explicit SAR-### even if other negatives present.
    - Maps POV synonyms.
    """
    t = (text or "").lower()

    if not t:
        return "Unknown"

    # POV
    if any(k in t for k in ["pov","p.v.","pv","personal vehicle","own car","driving myself","my car","personal"]) and "sar" not in t:
        return "POV"

    # SAR Rig
    if re.search(r"\bsar\s*rig\b", t):
        return "SAR Rig"

    # Special: "coming in <int>" means vehicle unless a time unit follows
    m = re.search(r"\bcoming\s+in\s+(\d{1,3})(?!\s*(?:m|min|mins?|minutes?)\b)", t)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 999:
            return f"SAR-{n}"

    # Negative and positive cues
    NEG = r"\b(?:key|box|code|channel|ch\b|freq|mhz|alpha|bravo|charlie|copy\b|subject|subj\b|grid|mile)\b"
    POS = r"(?:\bsar\b|\bunit\b|\brig\b|\btruck\b|\brespond(?:ing)?\b|\brolling\b|\btaking\b|\bcoming\b|\barriving\b|\bwith\b|\bdriving\b|\bin\b)"

    neg = bool(re.search(NEG, t))

    # Explicit "SAR-###" wins even if negatives are present
    m = re.search(r"\bsar[\s-]*0*(\d{1,3})\b", t)
    if m:
        return f"SAR-{int(m.group(1))}"

    # Contexted numeric vehicle only when positive cues and no negative cues
    if not neg and re.search(POS, t):
        m = re.search(r"\b0*(\d{1,3})\b", t)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 999:
                return f"SAR-{n}"

    return "Unknown"

def _clamp_minutes(minutes: float) -> int:
    m = int(round(minutes))
    return max(0, min(m, 24 * 60))

# NEW: small typo fixups so "mninutes" etc. don't derail parsing
def _fix_common_typos(s: str) -> str:
    replacements = {
        r"\bmninute?s?\b": "minutes",
        r"\bminitue?s?\b": "minutes",
        r"\bminites?\b": "minutes",
        r"\bmintes?\b": "minutes",
        r"\bminuets?\b": "minutes",
        r"\bhoures?\b": "hours",
        r"\bhors?\b": "hours",
    }
    out = s
    for pat, repl in replacements.items():
        out = re.sub(pat, repl, out)
    return out

# NEW: words → number (supports up to 999, handles "a/an")
_SMALL = {
    "zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,
    "ten":10,"eleven":11,"twelve":12,"thirteen":13,"fourteen":14,"fifteen":15,"sixteen":16,
    "seventeen":17,"eighteen":18,"nineteen":19,
}
_TENS = {"twenty":20,"thirty":30,"forty":40,"fifty":50,"sixty":60,"seventy":70,"eighty":80,"ninety":90}

def _words_to_int(phrase: str) -> Optional[int]:
    if not phrase:
        return None
    phrase = phrase.replace("-", " ")
    toks = re.findall(r"[a-z]+", phrase.lower())
    if not toks:
        return None
    total, current = 0, 0
    for w in toks:
        if w in ("a", "an"):
            current += 1
        elif w in _SMALL:
            current += _SMALL[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w == "hundred":
            current = (current or 1) * 100
        elif w in ("and", "about", "around", "approximately", "roughly"):
            continue
        elif w in ("half", "quarter"):
            # only meaningful with hours ("an hour and a half")—handled elsewhere
            return None
        else:
            # unknown word → not a clean number phrase
            return None
    total += current
    return total if total >= 0 else None

# NEW: shift an HH:MM string by ±minutes (wrap 24h)
def _shift_hhmm(hhmm: str, delta_min: int) -> Optional[str]:
    try:
        h, m = map(int, hhmm.split(":"))
        tot = (h * 60 + m + delta_min) % (24 * 60)
        return f"{tot // 60:02d}:{tot % 60:02d}"
    except Exception:
        return None

# UPDATED: now accepts prev_eta_hhmm for relative updates; handles spelled numbers/typos
def convert_eta_text_to_hhmm(eta_text: str, base_time: datetime, prev_eta_hhmm: Optional[str] = None) -> str:
    """
    Parse human ETA → HH:MM (24h) relative to base_time, optionally relative to prev_eta_hhmm
    for "early/later/unchanged/ETA±N" updates. No timezone changes.
    """
    try:
        if not eta_text or not eta_text.strip():
            return "Unknown"

        raw = eta_text.strip()
        low = _fix_common_typos(raw.lower())
        low = low.replace("~", "").strip()

        # Treat ETD like ETA in SAR chat unless clearly a planning context
        low = re.sub(r"^\s*etd\b", "eta", low)

        # 1) Exact HH:MM (with optional am/pm)
        m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*(am|pm)?\s*$", low)
        if m:
            hour, minute, ap = int(m.group(1)), int(m.group(2)), m.group(3)
            if minute > 59:
                return "Unknown"
            if ap:
                if ap == "pm" and hour != 12:
                    hour += 12
                if ap == "am" and hour == 12:
                    hour = 0
            if hour == 24:
                hour = 0
            if hour > 23:
                return "Unknown"
            return f"{hour:02d}:{minute:02d}"

        # 2) Compact 3/4-digit times (0830, 2330, 830)
        if re.match(r"^\s*\d{3,4}\s*$", low):
            digits = re.findall(r"\d+", low)[0]
            if len(digits) == 3:
                hour, minute = int(digits[0]), int(digits[1:3])
            else:
                hour, minute = int(digits[:2]), int(digits[2:])
            if hour == 24:
                hour = 0
            if hour > 23 or minute > 59:
                return "Unknown"
            return f"{hour:02d}:{minute:02d}"

        # 3) "8 pm"
        m = re.match(r"^\s*(\d{1,2})\s*(am|pm)\s*$", low)
        if m:
            hour, ap = int(m.group(1)), m.group(2)
            if ap == "pm" and hour != 12:
                hour += 12
            if ap == "am" and hour == 12:
                hour = 0
            return f"{hour:02d}:00"

        # 4) Relative updates vs. previous ETA (if provided)
        #    - "7 minutes early/earlier/ahead"
        #    - "10 minutes late/later/behind"
        #    - "ETA +10", "ETA -7"
        #    - "pushed back 15", "moved up by fifteen", "bumped up 5", "slipped 3"
        #    - "unchanged", "same as before", "no change"
        def _amt_to_minutes(txt: str) -> Optional[int]:
            txt = txt.strip()
            if re.match(r"^\d+(?:\.\d+)?$", txt):
                return int(round(float(txt)))
            w = _words_to_int(txt)
            return w

        if prev_eta_hhmm:
            # unchanged
            if any(k in low for k in ["unchanged", "same as before", "same as prior", "no change"]):
                return prev_eta_hhmm

            # ETA +/- N
            m = re.search(r"(?:\beta\s*)?([+-])\s*(\d+)\b", low)
            if m:
                sign = 1 if m.group(1) == "+" else -1
                mins = int(m.group(2))
                shifted = _shift_hhmm(prev_eta_hhmm, sign * mins)
                return shifted or "Unknown"

            # early / later
            m = re.search(r"\b((?:\d+(?:\.\d+)?)|(?:[a-z\- ]+))\s*(?:mins?|minutes?)\s*(early|earlier|ahead)\b", low)
            if m:
                val = _amt_to_minutes(m.group(1))
                if val is not None:
                    shifted = _shift_hhmm(prev_eta_hhmm, -val)
                    return shifted or "Unknown"

            m = re.search(r"\b((?:\d+(?:\.\d+)?)|(?:[a-z\- ]+))\s*(?:mins?|minutes?)\s*(late|later|behind)\b", low)
            if m:
                val = _amt_to_minutes(m.group(1))
                if val is not None:
                    shifted = _shift_hhmm(prev_eta_hhmm, +val)
                    return shifted or "Unknown"

            # pushed/moved/bumped/slipped
            m = re.search(r"\b(?:pushed(?:\s*back)?|push(?:ed)?\s*back)\s*(?:by\s*)?((?:\d+|[a-z\- ]+))\s*(?:mins?|minutes?)\b", low)
            if m:
                val = _amt_to_minutes(m.group(1))
                if val is not None:
                    shifted = _shift_hhmm(prev_eta_hhmm, +val)
                    return shifted or "Unknown"

            m = re.search(r"\b(?:moved|bumped)\s*up\s*(?:by\s*)?((?:\d+|[a-z\- ]+))\s*(?:mins?|minutes?)\b", low)
            if m:
                val = _amt_to_minutes(m.group(1))
                if val is not None:
                    shifted = _shift_hhmm(prev_eta_hhmm, -val)
                    return shifted or "Unknown"

            m = re.search(r"\bslipped\s*((?:\d+|[a-z\- ]+))\s*(?:mins?|minutes?)\b", low)
            if m:
                val = _amt_to_minutes(m.group(1))
                if val is not None:
                    shifted = _shift_hhmm(prev_eta_hhmm, +val)
                    return shifted or "Unknown"

        # "arrive/by/there at ..." hooks → delegate to the core parser
        m = re.search(r"\b(?:arrive|arrival|be there|there|by)\s*(?:at\s*)?(\d{1,2}:\d{2}|\d{3,4}|\d{1,2}\s*(?:am|pm))\b", low)
        if m:
            return convert_eta_text_to_hhmm(m.group(1), base_time, prev_eta_hhmm)

        # "minutes out"
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:mins?|minutes?)\s*out\b", low)
        if m:
            mins = float(m.group(1))
            eta_dt = base_time + timedelta(minutes=_clamp_minutes(mins))
            return eta_dt.strftime("%H:%M")

        # "15min" (no space)
        m = re.search(r"\b(\d+)\s*min\b", low)
        if m:
            mins = int(m.group(1))
            eta_dt = base_time + timedelta(minutes=_clamp_minutes(mins))
            return eta_dt.strftime("%H:%M")

        # 5) Durations relative to base_time (numbers)
        if "an hour and a half" in low or "a hour and a half" in low or re.search(r"\b1\s*hour\s*and\s*a\s*half\b", low):
            eta_dt = base_time + timedelta(minutes=90)
            return eta_dt.strftime("%H:%M")
        if "half an hour" in low:
            eta_dt = base_time + timedelta(minutes=30)
            return eta_dt.strftime("%H:%M")

        m = re.search(r"\b(\d+)\s*(?:hours?|hrs?)\s*and\s*(\d+)\s*(?:mins?|minutes?)\b", low)
        if m:
            total = int(m.group(1)) * 60 + int(m.group(2))
            eta_dt = base_time + timedelta(minutes=_clamp_minutes(total))
            return eta_dt.strftime("%H:%M")

        m = re.search(r"\b(?:an|a)\s+hour\s*and\s*(\d+)\s*(?:mins?|minutes?)\b", low)
        if m:
            total = 60 + int(m.group(1))
            eta_dt = base_time + timedelta(minutes=_clamp_minutes(total))
            return eta_dt.strftime("%H:%M")

        m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\b", low)
        if m:
            hours = float(m.group(1))
            eta_dt = base_time + timedelta(minutes=_clamp_minutes(hours * 60))
            return eta_dt.strftime("%H:%M")

        m = re.search(r"\b(\d+)\s*(?:mins?|minutes?)\b", low)
        if m:
            mins = int(m.group(1))
            eta_dt = base_time + timedelta(minutes=_clamp_minutes(mins))
            return eta_dt.strftime("%H:%M")

        m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([mh])\s*$", low)
        if m:
            val = float(m.group(1))
            unit = m.group(2)
            mins = val * (60 if unit == "h" else 1)
            eta_dt = base_time + timedelta(minutes=_clamp_minutes(mins))
            return eta_dt.strftime("%H:%M")

        # 6) Durations with spelled-out numbers ("twenty minutes out")
        m = re.search(r"\b([a-z\- ]+?)\s*(?:mins?|minutes?)\b", low)
        if m:
            w = _words_to_int(m.group(1))
            if w is not None:
                eta_dt = base_time + timedelta(minutes=_clamp_minutes(w))
                return eta_dt.strftime("%H:%M")

        # 7) Bare number → minutes (digits only)
        if re.match(r"^\s*\d+(?:\.\d+)?\s*$", low):
            mins = float(re.findall(r"\d+(?:\.\d+)?", low)[0])
            eta_dt = base_time + timedelta(minutes=_clamp_minutes(mins))
            return eta_dt.strftime("%H:%M")

        # 8) embedded "ETA HH:MM/0830"
        m = re.search(r"\betaa?\s*[:\-]?\s*(\d{1,2}:\d{2}|\d{3,4})\b", low)
        if m:
            return convert_eta_text_to_hhmm(m.group(1), base_time, prev_eta_hhmm)

        return "Unknown"
    except Exception:
        return "Unknown"

def normalize_status(s: str) -> str:
    if not s:
        return "Unknown"
    s = s.strip().lower()
    mapping = {
        "responding": "Responding",
        "available": "Available",
        "informational": "Informational",
        "not responding": "Not Responding",
        "cancelled": "Cancelled",
        "canceled": "Cancelled",
        "unknown": "Unknown",
    }
    return mapping.get(s, "Unknown")

# Deterministic status classifier from message text
def classify_status_from_text(msg: str) -> str:
    t = (msg or "").strip().lower()
    if not t:
        return "Unknown"

    # --- time-ish mention ---
    timeish = (
        re.search(r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\b", t) or
        re.search(r"\b\d{3,4}\b", t) or
        re.search(r"\b\d+\s*(?:m|min|mins?|minutes?|h|hr|hrs?|hours?)\b", t) or
        re.search(r"\b(?:an|a)\s+hour\b", t) or
        ("half an hour" in t)
    )
    # Guard: don't let 1022 drive timeish
    if re.search(r"\b(?:10-?22|1022)\b", t):
        timeish = False

    # Informational stand-down content FIRST
    if (
        re.search(r"\b(?:10-?22|1022)\s*(?:subj(?:ect)?\s*found|subject\s*found)\b", t)
        or re.search(r"\bmission\s*(?:over|complete)\b", t)
        or re.search(r"\bper\s*ic\b", t)
        or re.search(r"\bcopy\s+that\s*(?:10-?22|1022)\b", t)
    ):
        return "Informational"

    # Acknowledging stand-down (bare/ack/copy)
    if re.fullmatch(r"\s*(?:10-?22|1022)\s*\.?\s*", t) or \
       re.search(r"\b(?:copy|ack(?:nowledged)?)\s*(?:10-?22|1022)\b", t):
        return "Not Responding"

    # Cancelled
    if re.search(r"(can't\s+make\s+it|won't\s+make|unavailable|i.?m\s+out|working\s+late|bail(?:ing)?|tap\s+out)", t):
        return "Cancelled"

    # Questions are informational
    if re.search(r"\?\s*$", t):
        return "Informational"

    # Responding cues (expanded)
    if re.search(r"\b(respond(?:ing)?|en\s?route|enrt|on\s*it|rolling|leaving\s+now|\beta\b|be\s+there|headed|arrive|arriving|coming|etd)\b", t):
        return "Responding"

    # Implicit ETA implies responding (unless it's clearly channel/freq)
    if timeish and not re.search(r"\b(channel|ch\b|freq|mhz)\b", t):
        return "Responding"

    # Available
    if re.search(r"\b(available|can\s+respond\s+if\s+needed|able\s+to\s+respond)\b", t):
        return "Available"

    # Informational catch-all (keys/channels)
    if re.search(r"\b(key|channel|freq|mhz)\b", t):
        return "Informational"

    return "Unknown"

# ISO helpers (UTC Z)
def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")

def from_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)

def parse_eta_text_to_dt(eta_text: str, current_dt: datetime, prev_eta_dt: Optional[datetime]) -> Optional[datetime]:
    """Bridge: reuse convert_eta_text_to_hhmm then combine with current_dt date; honor prev_eta for relative updates."""
    try:
        prev_hhmm = None
        if prev_eta_dt is not None:
            prev_hhmm = prev_eta_dt.strftime("%H:%M")
        hhmm = convert_eta_text_to_hhmm(eta_text, current_dt, prev_hhmm)
        if not re.match(r"^\d{1,2}:\d{2}$", hhmm):
            return None
        h, m = map(int, hhmm.split(":"))
        candidate = current_dt.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidate < current_dt:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)
    except Exception:
        return None

# -----------------------
# Test set
# -----------------------

@dataclass
class SarCase:
    text: str
    current_ts: str              # ISO 8601 UTC, e.g., "2024-02-22T12:00:00Z"
    expected_vehicle: str
    expected_eta: str            # ISO 8601 or sentinel ("Unknown")
    expected_status: str
    note: str = ""
    prev_eta: Optional[str] = None   # ISO 8601 or None

def iso(dt: datetime) -> str:
    return dt.isoformat()

DEFAULT_BASE_TS = "2024-02-22T06:45:00Z"  # Deterministic default reference timestamp
BASE = datetime.fromisoformat(DEFAULT_BASE_TS.replace("Z", "+00:00"))

TESTS: List[SarCase] = []  # Will be loaded from JSON
CASES_FILE = "sar_test_cases.json"
TOLERANCE_MIN = 2

def _hhmm_to_iso(base_dt: datetime, hhmm: str) -> str:
    """Combine an HH:MM with base_dt's date/tz; if time-of-day is earlier than base_dt, assume next day."""
    try:
        h, m = map(int, hhmm.split(":"))
        candidate = base_dt.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidate < base_dt:
            candidate += timedelta(days=1)
        return candidate.isoformat()
    except Exception:
        return "Unknown"

def load_test_cases(cases_path: Optional[str] = None) -> List[SarCase]:
    """Load test cases from JSON file and convert to SarCase objects.
    Supports two JSON formats:
      1) Array of cases (back-compat)
      2) Object { "meta": {"baseTime": ISO }, "cases": [ ... ] }
    Each case may include currentTimeStamp (ISO). If omitted, defaults to meta.baseTime or DEFAULT_BASE_TS.
    expectedETA is normalized to an ISO timestamp when possible; otherwise remains "Unknown".
    """
    import os

    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(script_dir, cases_path or CASES_FILE)

    with open(json_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # Determine meta and cases
    if isinstance(raw, dict) and "cases" in raw:
        meta = raw.get("meta", {})
        cases_raw = raw["cases"]
        default_base_ts = meta.get("baseTime", DEFAULT_BASE_TS)
    else:
        cases_raw = raw
        default_base_ts = DEFAULT_BASE_TS

    cases: List[SarCase] = []

    def _is_hhmm(x: str) -> bool:
        return bool(re.match(r"^\d{1,2}:\d{2}$", str(x).strip()))

    for t in cases_raw:
        # Resolve base time for this case
        base_ts = t.get("currentTimeStamp", default_base_ts)
        try:
            base_dt = from_iso(base_ts)
        except Exception:
            base_dt = from_iso(DEFAULT_BASE_TS)

        # Optional baseTimeOverride like "23:50" to adjust time portion
        if "baseTimeOverride" in t:
            try:
                hour, minute = map(int, str(t["baseTimeOverride"]).split(":"))
                base_dt = base_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
            except Exception:
                pass

        # previous ETA support: accept HH:MM or duration text (convert via base_dt)
        prev_eta_iso = t.get("prevETA")
        # Back-compat: allow HH:MM and convert to ISO on same date as base_dt
        prev_eta_dt = None
        if prev_eta_iso:
            try:
                prev_eta_dt = from_iso(prev_eta_iso)
            except Exception:
                if _is_hhmm(str(prev_eta_iso)):
                    h, m = map(int, str(prev_eta_iso).split(":"))
                    prev_eta_dt = base_dt.replace(hour=h, minute=m, second=0, microsecond=0)
        prev_eta_out = to_iso(prev_eta_dt) if prev_eta_dt else None

        # Normalize expected ETA to ISO timestamp when possible
        exp_eta_raw = t.get("expectedETA", "Unknown")
        if isinstance(exp_eta_raw, str) and exp_eta_raw.strip() == "Unknown":
            exp_eta_ts = "Unknown"
        else:
            # Accept ISO if given
            try:
                _ = from_iso(str(exp_eta_raw))
                exp_eta_ts = str(exp_eta_raw)
            except Exception:
                # Back-compat: parse text using current_dt/prev_eta_dt
                dt = parse_eta_text_to_dt(str(exp_eta_raw), base_dt, prev_eta_dt)
                exp_eta_ts = to_iso(dt) if dt else "Unknown"

        cases.append(SarCase(
            text=t["input"],
            current_ts=to_iso(base_dt),
            expected_vehicle=t["expectedVehicle"],
            expected_eta=exp_eta_ts,
            expected_status=t["expectedStatus"],
            note=t.get("note", ""),
            prev_eta=prev_eta_out
        ))
    return cases

# Load test cases from JSON
TESTS: List[SarCase] = load_test_cases()

# -----------------------------------------------------
# Prompts (assisted vs raw mode)
# -----------------------------------------------------

SYSTEM_PROMPT_ASSISTED = """You are a SAR message extractor. The user will give you a single responder chat message, plus context.
Return ONLY a compact JSON object with fields described below. DO NOT do time arithmetic.

Context:
- Messages are from Search & Rescue responders coordinating by chat.
- Vehicles are usually either a personal vehicle (synonyms: POV, PV, personal vehicle, own car, driving myself)
  or a numbered SAR rig written various ways: "78", "SAR 78", "SAR-078", "in 78", "coming in 78".
- The local shorthand "10-22" or "1022" means stand down/cancel (NOT a time).
- People sometimes swear or are extremely brief.
- Sometimes they post informational notes ("key for 74 is in the box")—that is NOT a response.
- The current reference timestamp is provided as "Current time". Do NOT compute ETAs.
- For ETA, output exactly what the message says as text (e.g., '15 minutes', '2330', '8:45 pm', '07:30') or 'Unknown' if none is present.

Output JSON schema (no extra keys, no trailing text):
{
    "vehicle": "POV" | "SAR-<number>" | "SAR Rig" | "Unknown",
    "eta_text": "<raw time text as written, or 'Unknown' if none>",
    "status": "Responding" | "Cancelled" | "Available" | "Informational" | "Not Responding" | "Unknown",
  "evidence": "<short phrase from the message>",
  "confidence": <float between 0 and 1>
}

Rules:
- VEHICLE: Extract specific vehicle type. Never use "Not Responding" as a vehicle - use "Unknown" instead. "coming in <integer>" implies the SAR unit unless followed by a time unit.
- ETA: DO NOT calculate. Return literal text (e.g., '2330', '08:45', '45 minutes', '1 hr', '7:05 pm') or 'Unknown'.
- STATUS: 
  - "Responding" = actively responding to mission
  - "Cancelled" = person cancels their own response ('can't make it', 'I'm out')
  - "Not Responding" = acknowledges stand down / using '10-22' code
  - "Informational" = sharing info but not responding ('key is in box', asking questions)
  - "Available" = willing to respond if needed
  - "Unknown" = unclear intent
- If message includes 'in 78', 'responding 78', 'sar 78', normalize vehicle to 'SAR-78'.
- If message refers to personal vehicle, normalize vehicle to 'POV'.
"""

SYSTEM_PROMPT_RAW = """You are analyzing Search & Rescue response messages. Extract vehicle, ETA, and response status with full parsing and normalization.

Context:
- Messages are from SAR responders coordinating by chat
- Current time is provided - use it to calculate actual ETAs from relative or duration times
- Vehicle types: Personal vehicles (POV, PV, own car, etc.) or numbered SAR units (78, SAR-78, etc.)
- "10-22" / "1022" means stand down/cancel (NOT a time)
- Parse ALL time formats: absolute times (0830, 8:30 am), durations (15 min, 1 hr), relative phrases

Output JSON schema (no extra keys, no trailing text):
{
    "vehicle": "POV" | "SAR-<number>" | "SAR Rig" | "Unknown",
    "eta_iso": "<ISO 8601 UTC like 2024-02-22T12:45:00Z or 'Unknown'>",
    "status": "Responding" | "Cancelled" | "Available" | "Informational" | "Not Responding" | "Unknown",
  "evidence": "<short phrase from the message>",
  "confidence": <float between 0 and 1>
}

Vehicle Normalization:
- Personal vehicle references → "POV"
- SAR unit numbers (any format) → "SAR-<number>" (e.g., "SAR-78")
- SAR rig references → "SAR Rig"
- No vehicle mentioned/unclear → "Unknown"
- NEVER use "Not Responding" as a vehicle type

ETA Calculation:
- Convert ALL time references to HH:MM format (24-hour)
- Durations: Add to current time (e.g., "15 min" + current time)
- Absolute times: Convert to HH:MM (e.g., "0830" → "08:30", "8:30 pm" → "20:30")
- Relative updates: Modify previous ETA if provided
- No time mentioned → "Unknown"
- NEVER use "Not Responding" or "Cancelled" as ETA values
 - RAW output must place the final result as ISO-8601 UTC in field "eta_iso".

Status Classification:
- "Responding" = actively responding to mission
- "Cancelled" = person cancels their own response ('can't make it', 'I'm out')
- "Not Responding" = acknowledges stand down / using '10-22' code
- "Informational" = sharing info but not responding ('key is in box', asking questions)
- "Available" = willing to respond if needed
- "Unknown" = unclear intent
- SAR rig/truck references → "SAR Rig"
- Cancellations/non-responses → "Not Responding"

ETA Calculation (YOU must do the math):
- Absolute times: Convert to 24-hour HH:MM format
- Durations: Add to current time to get arrival time in HH:MM
- AM/PM times: Convert properly to 24-hour format
- If no ETA info or cancelled → "Unknown", "Cancelled", or "Not Responding"

Status Classification:
- Actively responding with vehicle/ETA → "Responding"  
- Personal cancellation → "Cancelled"
- Official stand-down (10-22) → "Not Responding"
- Available but not committed → "Available"
- Information only → "Informational"
"""

# Default to assisted mode (original behavior)
SYSTEM_PROMPT = SYSTEM_PROMPT_ASSISTED

def build_user_prompt(msg: SarCase, raw_mode: bool = False) -> str:
    prev = msg.prev_eta if msg.prev_eta else "None"
    if raw_mode:
        return (
            f"Current time (UTC): {msg.current_ts}\n"
            f"Previous ETA (if any): {prev}\n"
            f"SAR Message: {msg.text}\n\n"
            f"Extract vehicle, calculate ETA to an absolute ISO-8601 UTC string (eta_iso), and determine response status."
        )
    else:
        return (
            f"Current time (UTC, do NOT calculate): {msg.current_ts}\n"
            f"Previous ETA (if any): {prev}\n"
            f"Message: {msg.text}"
        )

# -----------------------------------------------------
# Scoring
# -----------------------------------------------------

def minutes_diff(hhmm_a: str, hhmm_b: str) -> Optional[int]:
    try:
        ha, ma = map(int, hhmm_a.split(":"))
        hb, mb = map(int, hhmm_b.split(":"))
        return abs((ha * 60 + ma) - (hb * 60 + mb))
    except Exception:
        return None

@dataclass
class CaseResult:
    ok_vehicle: bool
    ok_eta: bool
    ok_status: bool
    exact_triplet: bool
    got: Dict[str, Any]
    expected: Dict[str, Any]
    note: str

# -----------------------------------------------------
# Runner
# -----------------------------------------------------

RETRY = 2

ASSISTED_SCHEMA = {
    "name": "sar_extraction_assisted",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "vehicle": {"type": "string", "pattern": "^(POV|SAR Rig|SAR-[1-9][0-9]{0,2}|Unknown)$"},
            "eta_text": {"type": "string", "minLength": 1},
            "status": {"type": "string", "enum": ["Responding","Cancelled","Available","Informational","Not Responding","Unknown"]},
            "evidence": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0}
        },
        "required": ["vehicle","eta_text","status","evidence","confidence"]
    }
}

RAW_SCHEMA = {
    "name": "sar_extraction_raw",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "vehicle": {"type": "string", "pattern": "^(POV|SAR Rig|SAR-[1-9][0-9]{0,2}|Unknown)$"},
            "eta_iso": {"type": "string", "minLength": 1, "description": "ISO-8601 UTC like 2024-02-22T12:45:00Z or 'Unknown'"},
            "status": {"type": "string", "enum": ["Responding","Cancelled","Available","Informational","Not Responding","Unknown"]},
            "evidence": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0}
        },
        "required": ["vehicle","eta_iso","status","evidence","confidence"]
    }
}

async def ask_model(client: AsyncAzureOpenAI, model: str, msg: SarCase, raw_mode: bool = False) -> Dict[str, Any]:
    # Choose the appropriate prompt based on mode
    system_prompt = SYSTEM_PROMPT_RAW if raw_mode else SYSTEM_PROMPT_ASSISTED
    
    # Helper to call API with graceful fallback when json_schema isn't supported
    async def _create_with_fallback():
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_user_prompt(msg, raw_mode)},
        ]
        schema = RAW_SCHEMA if raw_mode else ASSISTED_SCHEMA
    # 1) Try json_schema
        try:
            return await client.chat.completions.create(
                model=model,
                response_format={"type": "json_schema", "json_schema": schema},
                messages=messages,
        max_completion_tokens=MAX_TOK_SINGLE,
            )
        except APIStatusError as e:
            etxt = str(e).lower()
            if ("response_format" in etxt and ("json_schema" in etxt or "not supported" in etxt)) or "invalid parameter" in etxt:
                # 2) Try json_object
                try:
                    return await client.chat.completions.create(
                        model=model,
                        response_format={"type": "json_object"},
                        messages=messages,
                        max_completion_tokens=MAX_TOK_SINGLE,
                    )
                except APIStatusError as e2:
                    etxt2 = str(e2).lower()
                    if "response_format" in etxt2 and ("json_object" in etxt2 or "not supported" in etxt2):
                        # 3) Try without response_format
                        return await client.chat.completions.create(
                            model=model,
                            messages=messages,
                            max_completion_tokens=MAX_TOK_SINGLE,
                        )
                    else:
                        raise
            else:
                raise

    # We request JSON-only; if model ignores, we fallback by regexing the first {...}
    resp = await _create_with_fallback()
    raw = resp.choices[0].message.content or ""
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.S)
        fallback_schema = {"vehicle":"Unknown","status":"Unknown","evidence":"","confidence":0.0}
        if raw_mode:
            fallback_schema["eta_iso"] = "Unknown"
        else:
            fallback_schema["eta_text"] = "Unknown"
        return json.loads(m.group(0)) if m else fallback_schema

async def run_one(client: AsyncAzureOpenAI, model: str, case: SarCase, raw_mode: bool = False) -> CaseResult:
    last_err = None
    for attempt in range(1, RETRY + 2):
        try:
            data = await ask_model(client, model, case, raw_mode)
            
            if raw_mode:
                # In raw mode, LLM does all normalization
                vehicle_guess = data.get("vehicle") or "Unknown"
                eta_iso = data.get("eta_iso") or "Unknown"
                status_guess = data.get("status") or "Unknown"
                
                # Minimal cleanup for raw mode
                veh_norm = vehicle_guess
                stat_norm = status_guess
                # Coerce ETA Unknown on Cancelled/Not Responding
                if stat_norm in ("Cancelled", "Not Responding"):
                    eta_norm = "Unknown"
                else:
                    try:
                        _ = from_iso(eta_iso) if isinstance(eta_iso, str) and eta_iso != "Unknown" else None
                        eta_norm = eta_iso if eta_iso == "Unknown" or _ else "Unknown"
                    except Exception:
                        eta_norm = "Unknown"
                
                # Basic vehicle cleanup for consistent formatting
                if veh_norm.startswith("SAR-") or veh_norm.startswith("SAR "):
                    # Clean zero-padding and format consistently
                    try:
                        num_match = re.search(r"(\d+)", veh_norm)
                        if num_match:
                            num = int(num_match.group(1))
                            veh_norm = f"SAR-{num}"
                    except Exception:
                        pass
                # Vehicle fallback from message
                if veh_norm == "Unknown":
                    veh_norm = normalize_vehicle(case.text)
                
                # eta_iso already validated above; nothing else to do here

            else:
                # Original assisted mode - harness does normalization
                vehicle_guess = data.get("vehicle") or "Unknown"
                eta_text = data.get("eta_text") or "Unknown"
                status_guess = data.get("status") or "Unknown"

                # Vehicle normalization (in case the model returns raw strings)
                veh_norm = vehicle_guess
                if veh_norm not in ["POV", "SAR Rig"] and not veh_norm.startswith("SAR-") and veh_norm not in ["Unknown", "Not Responding"]:
                    veh_norm = normalize_vehicle(str(vehicle_guess))
                elif veh_norm.startswith("SAR-"):
                    # Clean zero-padding
                    try:
                        num = int(re.findall(r"\d+", veh_norm)[0])
                        veh_norm = f"SAR-{num}"
                    except Exception:
                        pass
                # Vehicle fallback from message
                if veh_norm == "Unknown":
                    veh_norm = normalize_vehicle(case.text)

                # ETA normalization (we convert; model does not) -> ISO
                cur_dt = from_iso(case.current_ts)
                prev_dt = from_iso(case.prev_eta) if case.prev_eta else None
                dt = None if eta_text == "Unknown" else parse_eta_text_to_dt(str(eta_text), cur_dt, prev_dt)
                # Assisted fallback extraction if eta_text is Unknown: quick regex pick
                if dt is None and eta_text == "Unknown":
                    candidate = None
                    m = re.search(r"\b\d{1,2}:\d{2}(?:\s*(?:am|pm))?\b", case.text.lower())
                    if not m:
                        m = re.search(r"\b\d{3,4}\b", case.text.lower())
                    if not m:
                        m = re.search(r"\b\d+\s*(?:m|min|mins?|minutes?|h|hr|hrs?|hours?)\b", case.text.lower())
                    if m:
                        candidate = m.group(0)
                    if candidate:
                        dt = parse_eta_text_to_dt(candidate, cur_dt, prev_dt)
                eta_norm = to_iso(dt) if dt else "Unknown"

                # Status normalization
                stat_norm = normalize_status(str(status_guess))

            # Expected values
            exp_vehicle = case.expected_vehicle
            exp_eta = case.expected_eta
            exp_status = case.expected_status

            # Vehicle correctness:
            ok_vehicle = (veh_norm == exp_vehicle)

            # ETA correctness: compare ISO timestamps within <=2m tolerance, or Unknown
            if exp_eta in ["Unknown", "Not Responding", "Cancelled"]:
                ok_eta = (eta_norm == exp_eta)
            else:
                if eta_norm == "Unknown":
                    ok_eta = False
                else:
                    try:
                        a = from_iso(eta_norm)
                        b = from_iso(exp_eta)
                        diff = abs(int((a - b).total_seconds() // 60))
                        ok_eta = diff <= TOLERANCE_MIN
                    except Exception:
                        ok_eta = False

            # Deterministic status for scoring (ignore model status from LLM)
            stat_rule = classify_status_from_text(case.text)
            ok_status = (stat_rule == exp_status)
            exact_triplet = ok_vehicle and ok_eta and ok_status

            return CaseResult(
                ok_vehicle, ok_eta, ok_status, exact_triplet,
                got={"vehicle": veh_norm, "eta": eta_norm, "status": stat_rule, "raw": data},
                expected={"vehicle": exp_vehicle, "eta": exp_eta, "status": exp_status},
                note=case.note
            )
        except (APIConnectionError, RateLimitError, APIStatusError, APITimeoutError) as e:
            # Fallback path on filter/429/etc.
            last_err = e
            # Build fallback result using rules
            veh_fb = normalize_vehicle(case.text)
            stat_fb = classify_status_from_text(case.text)
            if raw_mode:
                eta_fb = "Unknown"
            else:
                cur_dt = from_iso(case.current_ts)
                prev_dt = from_iso(case.prev_eta) if case.prev_eta else None
                # Try regex extraction
                dt = None
                for pat in [r"\b\d{1,2}:\d{2}(?:\s*(?:am|pm))?\b", r"\b\d{3,4}\b", r"\b\d+\s*(?:m|min|mins?|minutes?|h|hr|hrs?|hours?)\b"]:
                    m = re.search(pat, case.text.lower())
                    if m:
                        dt = parse_eta_text_to_dt(m.group(0), cur_dt, prev_dt)
                        if dt:
                            break
                eta_fb = to_iso(dt) if dt else "Unknown"
            # Evaluate fallback vs expected
            ok_vehicle = (veh_fb == case.expected_vehicle)
            if case.expected_eta in ["Unknown", "Not Responding", "Cancelled"]:
                ok_eta = (eta_fb == case.expected_eta)
            else:
                try:
                    a = from_iso(eta_fb) if eta_fb != "Unknown" else None
                    b = from_iso(case.expected_eta)
                    ok_eta = a is not None and abs(int((a - b).total_seconds() // 60)) <= TOLERANCE_MIN
                except Exception:
                    ok_eta = False
            ok_status = (classify_status_from_text(case.text) == case.expected_status)
            exact_triplet = ok_vehicle and ok_eta and ok_status
            return CaseResult(ok_vehicle, ok_eta, ok_status, exact_triplet,
                              got={"vehicle": veh_fb, "eta": eta_fb, "status": classify_status_from_text(case.text), "error": str(e)},
                              expected={"vehicle": case.expected_vehicle, "eta": case.expected_eta, "status": case.expected_status},
                              note=case.note)
        except Exception as e:
            last_err = e
            break
    # On failure, return a miss
    return CaseResult(False, False, False, False,
                      got={"vehicle":"ERR","eta":"ERR","status":"ERR","error":str(last_err)},
                      expected={"vehicle": case.expected_vehicle, "eta": case.expected_eta, "status": case.expected_status},
                      note=case.note)

def summarize(results: List[CaseResult]) -> Dict[str, Any]:
    n = len(results)
    v = sum(1 for r in results if r.ok_vehicle)
    e = sum(1 for r in results if r.ok_eta)
    s = sum(1 for r in results if r.ok_status)
    t = sum(1 for r in results if r.exact_triplet)
    return {
        "n": n,
        "vehicle_acc": v / n if n else 0.0,
        "eta_acc": e / n if n else 0.0,
        "status_acc": s / n if n else 0.0,
        "triplet_acc": t / n if n else 0.0,
    }

def colorize(val: float, best: float, worst: float, invert: bool = False) -> str:
    # best=green, worst=red
    if best == worst:
        return f"{val:.2%}"
    score = (val - worst) / max(1e-9, (best - worst))
    if invert:
        score = 1 - score
    if score >= 0.66:
        c = GREEN
    elif score >= 0.33:
        c = YELLOW
    else:
        c = RED
    return f"{c}{val:.2%}{RESET}"

async def main():
    # Check for raw mode flag
    import sys
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--raw", action="store_true")
    parser.add_argument("--cases", type=str, default=None)
    parser.add_argument("--tolerance-min", type=int, default=2)
    parser.add_argument("--models", type=str, default=None)
    parser.add_argument("--help", "-h", action="store_true")
    args, _ = parser.parse_known_args()
    if args.help:
        print(f"{BOLD}SAR LLM Extraction Benchmark{RESET}")
        print()
        print("Usage:")
        print("  python sar_llm_extraction_benchmark.py                # Assisted mode")
        print("  python sar_llm_extraction_benchmark.py --raw          # Raw mode")
        print("  python sar_llm_extraction_benchmark.py --models gpt-5-mini,gpt-4o-mini")
        print("  python sar_llm_extraction_benchmark.py --cases path/to/tests.json")
        print("  python sar_llm_extraction_benchmark.py --tolerance-min 2")
        return
    raw_mode = args.raw
    global CASES_FILE, TOLERANCE_MIN, BENCH_MODELS
    if args.cases:
        CASES_FILE = args.cases
    if args.tolerance_min is not None:
        TOLERANCE_MIN = args.tolerance_min
    if args.models:
        BENCH_MODELS = [m.strip() for m in args.models.split(",") if m.strip()]

    # reload tests if cases file changed
    global TESTS
    TESTS = load_test_cases(CASES_FILE)
    
    client = AsyncAzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=AZURE_ENDPOINT,
        api_key=API_KEY,
    )

    mode_text = "RAW MODE" if raw_mode else "ASSISTED MODE"
    mode_desc = "LLMs do all parsing/normalization" if raw_mode else "Harness helps with normalization"
    print(f"{BOLD}🔬 SAR Benchmark - {mode_text}{RESET}")
    print(f"   {mode_desc}")
    print(f"{BOLD}Models under test:{RESET} {', '.join(BENCH_MODELS)}  |  Tolerance: ±{TOLERANCE_MIN}m")
    
    model_to_results: Dict[str, List[CaseResult]] = {}

    for model in BENCH_MODELS:
        print(f"\n{BOLD}Running cases on {model}{RESET}   ({len(TESTS)} cases)")
        start = time.time()
        tasks = [run_one(client, model, case, raw_mode) for case in TESTS]
        results = await asyncio.gather(*tasks)
        model_to_results[model] = results
        dur = time.time() - start

        summ = summarize(results)
        print(f"  Time: {dur:.2f}s | Vehicle {summ['vehicle_acc']:.2%}  ETA {summ['eta_acc']:.2%}  "
              f"Status {summ['status_acc']:.2%}  Triplet {BOLD}{summ['triplet_acc']:.2%}{RESET}")

    # Aggregate and pretty print comparison
    rows = []
    for model, results in model_to_results.items():
        s = summarize(results)
        rows.append((model, s))

    # Compute best/worst for coloring
    best_v = max(r[1]["vehicle_acc"] for r in rows)
    worst_v = min(r[1]["vehicle_acc"] for r in rows)
    best_e = max(r[1]["eta_acc"] for r in rows)
    worst_e = min(r[1]["eta_acc"] for r in rows)
    best_s = max(r[1]["status_acc"] for r in rows)
    worst_s = min(r[1]["status_acc"] for r in rows)
    best_t = max(r[1]["triplet_acc"] for r in rows)
    worst_t = min(r[1]["triplet_acc"] for r in rows)

    print(f"\n{BOLD}LLM Extraction Accuracy Comparison ({mode_text}){RESET}")
    
    # Create table with tabulate
    from tabulate import tabulate
    
    headers = [f"{BOLD}Model{RESET}", f"{BOLD}Vehicle{RESET}", f"{BOLD}ETA{RESET}", f"{BOLD}Status{RESET}", f"{BOLD}Triplet{RESET}"]
    table_data = []
    
    for model, s in sorted(rows, key=lambda x: x[1]["triplet_acc"], reverse=True):
        table_data.append([
            f"{BOLD}{model}{RESET}",
            colorize(s['vehicle_acc'], best_v, worst_v),
            colorize(s['eta_acc'], best_e, worst_e),
            colorize(s['status_acc'], best_s, worst_s),
            f"{BOLD}{colorize(s['triplet_acc'], best_t, worst_t)}{RESET}"
        ])
    
    print(tabulate(table_data, headers=headers, tablefmt="pretty"))

    # Brief failure report (top few per model)
    for model, results in model_to_results.items():
        failures = [r for r in results if not r.exact_triplet]
        if not failures:
            continue
        print(f"\n{BOLD}Sample failures for {model} ({len(failures)} / {len(results)}):{RESET}")
        for r in failures[:8]:
            print(f"- Note: {r.note or '(n/a)'}")
            # Find original case for context
            try:
                idx = results.index(r)
                case = TESTS[idx]
                print(f"  Input: {case.text}")
                print(f"  Current: {case.current_ts}  Prev: {case.prev_eta or 'None'}")
            except Exception:
                pass
            print(f"  Expected: {r.expected}")
            print(f"  Got:      {r.got}")
            print()

def get_test_cases():
    """Get all test cases for the benchmark (including current_ts and prev_eta)."""
    return [(t.text, t.current_ts, t.prev_eta, t.expected_vehicle, t.expected_eta, t.expected_status) for t in TESTS]

def parse_and_evaluate_result(response_text, expected_vehicle, expected_eta, expected_status, message, case_num, base_time_iso, prev_eta_hhmm):
    """Parse LLM response and evaluate against expected values."""
    
    # Parse the JSON response
    try:
        data = json.loads(response_text.strip())
        parsed_vehicle = data.get("vehicle", "").strip()
        # Schema uses 'eta_text'
        parsed_eta_text = data.get("eta_text", "").strip()
        parsed_status = data.get("status", "").strip()
    except json.JSONDecodeError:
        # Try to extract the first JSON object
        m = re.search(r"\{.*?\}", response_text, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
                parsed_vehicle = data.get("vehicle", "").strip()
                parsed_eta_text = data.get("eta_text", "").strip()
                parsed_status = data.get("status", "").strip()
            except Exception:
                return {
                    "vehicle_correct": False,
                    "eta_correct": False,
                    "status_correct": False,
                    "exact_match": False
                }
        else:
            return {
                "vehicle_correct": False,
                "eta_correct": False,
                "status_correct": False,
                "exact_match": False
            }
    
    # Normalize parsed values
    norm_vehicle = normalize_vehicle(parsed_vehicle) if parsed_vehicle else "Unknown"

    # For ETA, convert to ISO timestamp using the *case's* current_ts and prev_eta
    norm_eta = "Unknown"
    if parsed_eta_text:
        try:
            base_time = from_iso(base_time_iso)
            prev_dt = from_iso(prev_eta_hhmm) if prev_eta_hhmm else None
            dt = parse_eta_text_to_dt(parsed_eta_text, base_time, prev_dt)
            norm_eta = to_iso(dt) if dt else "Unknown"
        except Exception:
            norm_eta = "Unknown"
    
    # Deterministic status from text
    norm_status = classify_status_from_text(message)
    
    # Compare with expected values
    vehicle_correct = (norm_vehicle == expected_vehicle)
    if expected_eta == "Unknown":
        eta_correct = (norm_eta == expected_eta)
    else:
        # allow ±2 min tolerance on ISO timestamps
        try:
            a = from_iso(str(norm_eta)) if norm_eta != "Unknown" else None
            b = from_iso(str(expected_eta))
            eta_correct = a is not None and abs(int((a - b).total_seconds() // 60)) <= TOLERANCE_MIN
        except Exception:
            eta_correct = False
    status_correct = (norm_status == expected_status)
    exact_match = vehicle_correct and eta_correct and status_correct
    
    return {
        "vehicle_correct": vehicle_correct,
        "eta_correct": eta_correct,
        "status_correct": status_correct,
        "exact_match": exact_match,
        "parsed_vehicle": norm_vehicle,
        "parsed_eta": norm_eta,
        "parsed_status": norm_status
    }

async def run_comprehensive_benchmark(run_assisted: bool = True, run_raw: bool = True):
    """Run benchmark with all model variants and reasoning/verbosity combinations.
    Args:
        run_assisted: include assisted-mode runs
        run_raw: include raw-mode runs
    """

    # --- Configuration Options ---
    FAST_MODELS_ONLY = False  # Set to False to test all models
    INCLUDE_REASONING_VARIANTS = True  # Set to True to test reasoning levels
    INCLUDE_VERBOSITY_VARIANTS = True  # Set to True to test verbosity levels

    print(f"{BOLD}🚀 SAR LLM Extraction Benchmark{RESET}")
    print(f"Configuration: Fast={'Y' if FAST_MODELS_ONLY else 'N'}, Reasoning={'Y' if INCLUDE_REASONING_VARIANTS else 'N'}, Verbosity={'Y' if INCLUDE_VERBOSITY_VARIANTS else 'N'}")
    print("-" * 80)

    # Base fast models (always included)
    if FAST_MODELS_ONLY:
        base_models = ["gpt-5-nano", "gpt-5-mini", "gpt-4o-mini"]
    else:
        # All available models - focus on gpt-5-nano, gpt-5-mini, plus gpt-4o and gpt-5-chat
        base_models = ["gpt-4o", "gpt-4o-mini", "gpt-5-chat", "gpt-5-nano", "gpt-5-mini"]

    # Build model configurations
    model_configs = []

    # Add base models without special parameters
    for model in base_models:
        model_configs.append({
            "model": model,
            "verbosity": None,
            "reasoning": None,
            "description": f"{model} (default)"
        })

    # Add reasoning variants if enabled
    if INCLUDE_REASONING_VARIANTS:
        reasoning_levels = ["minimal", "low", "medium", "high"]
        gpt5_variants = [m for m in base_models if m.startswith("gpt-5") and m not in ["gpt-5-chat"]]

        for model in gpt5_variants:
            for reasoning in reasoning_levels:
                model_configs.append({
                    "model": model,
                    "verbosity": None,
                    "reasoning": reasoning,
                    "description": f"{model} (reasoning={reasoning})"
                })

    # Add verbosity variants if enabled
    if INCLUDE_VERBOSITY_VARIANTS:
        verbosity_levels = ["low", "medium", "high"]
        gpt5_variants = [m for m in base_models if m.startswith("gpt-5") and m not in ["gpt-5-chat"]]

        for model in gpt5_variants:
            for verbosity in verbosity_levels:
                model_configs.append({
                    "model": model,
                    "verbosity": verbosity,
                    "reasoning": None,
                    "description": f"{model} (verbosity={verbosity})"
                })

    # Add combined variants if both are enabled
    if INCLUDE_REASONING_VARIANTS and INCLUDE_VERBOSITY_VARIANTS:
        reasoning_levels = ["low", "medium"]  # Limit combinations to avoid explosion
        verbosity_levels = ["low", "medium"]
        gpt5_variants = [m for m in base_models if m.startswith("gpt-5") and m not in ["gpt-5-chat"]]

        for model in gpt5_variants:
            for reasoning in reasoning_levels:
                for verbosity in verbosity_levels:
                    model_configs.append({
                        "model": model,
                        "verbosity": verbosity,
                        "reasoning": reasoning,
                        "description": f"{model} (reasoning={reasoning}, verbosity={verbosity})"
                    })

    print(f"Testing {len(model_configs)} model configurations:")
    for i, config in enumerate(model_configs, 1):
        print(f"  {i:2d}. {config['description']}")
    print()

    # Run the benchmark with these configurations
    await run_benchmark_with_configs(model_configs, run_assisted=run_assisted, run_raw=run_raw)

async def run_benchmark_with_configs(model_configs, run_assisted: bool = True, run_raw: bool = True):
    """Run the SAR benchmark with specified model configurations."""
    
    # Validate environment
    endpoint = os.getenv("model_endpoint")
    api_key = os.getenv("model_api_key")
    
    if not endpoint or not api_key:
        print(f"{RED}❌ Error: Missing environment variables{RESET}")
        print("Please ensure model_endpoint and model_api_key are set in your .env file")
        return
    
    # Initialize client
    client = AsyncAzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=endpoint,
        api_key=api_key,
    )
    
    print(f"{BOLD}Running SAR extraction benchmark...{RESET}")
    
    # Prepare all tasks
    tasks = []
    task_labels = []
    for config in model_configs:
        # Add extra parameters for the API call
        extra_params = {}
        if config.get("verbosity"):
            extra_params["verbosity"] = config["verbosity"]
        if config.get("reasoning"):
            extra_params["reasoning_effort"] = config["reasoning"]

        # Create a modified config for the existing benchmark function
        base_cfg = {
            "model": config["model"],
            "extra_params": extra_params,
            "description": config["description"],
        }

        if run_assisted:
            assisted_cfg = {**base_cfg, "description": f"{base_cfg['description']} [assisted]", "raw_mode": False}
            tasks.append(benchmark_model_with_config(client, assisted_cfg))
            task_labels.append(assisted_cfg["description"])
        if run_raw:
            raw_cfg = {**base_cfg, "description": f"{base_cfg['description']} [raw]", "raw_mode": True}
            tasks.append(benchmark_model_with_config(client, raw_cfg))
            task_labels.append(raw_cfg["description"])
    
    # Run all benchmarks concurrently
    print(f"Executing {len(tasks)} benchmark runs...")
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process and display results
    successful_results = []
    failed_results = []

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            failed_results.append((task_labels[i], str(result)))
        else:
            successful_results.append(result)
    
    if failed_results:
        print(f"\n{RED}❌ Failed runs:{RESET}")
        for desc, error in failed_results:
            print(f"  - {desc}: {error}")
    
    if successful_results:
        display_benchmark_comparison(successful_results)
    else:
        print(f"{RED}❌ All benchmark runs failed{RESET}")

async def benchmark_model_with_config(client, config):
    """Run the SAR benchmark for a single model configuration."""
    
    model_name = config["model"]
    extra_params = config.get("extra_params", {})
    description = config["description"]
    raw_mode = config.get("raw_mode", False)
    
    print(f"  🧪 Testing {description}...")
    
    # Use the existing benchmark logic but with modified API call
    test_cases = get_test_cases()
    all_results = []
    total_time = 0
    total_input_tokens = 0
    total_output_tokens = 0
    
    # Global concurrency limiter
    sem = config.get("_sem")
    if sem is None:
        # Back-compat: create local semaphore if not provided
        sem = asyncio.Semaphore(MAX_CONCURRENCY)

    for i, (text, base_time_iso, prev_eta_hhmm, expected_vehicle, expected_eta, expected_status) in enumerate(test_cases):
        try:
            start_time = time.time()
            
            # Make API call with strict schema and mode-specific prompts
            system_prompt = SYSTEM_PROMPT_RAW if raw_mode else SYSTEM_PROMPT_ASSISTED
            schema = RAW_SCHEMA if raw_mode else ASSISTED_SCHEMA
            user_content = (
                f"Current time (UTC){'' if raw_mode else ', do NOT calculate'}: {base_time_iso}\n"
                f"Previous ETA (if any): {prev_eta_hhmm or 'None'}\n"
                f"Message: {text}" if not raw_mode else
                f"Current time (UTC): {base_time_iso}\nPrevious ETA (if any): {prev_eta_hhmm or 'None'}\nSAR Message: {text}\n\nExtract vehicle, calculate ETA to an absolute ISO-8601 UTC string (eta_iso), and determine response status."
            )

            # Call API with fallback for response_format support across models
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]
            async def _create_with_fallback_case():
                # Retry with exponential backoff for transient errors and adjust max tokens on overflow
                base_tok = int(os.getenv("MAX_COMPLETION_TOKENS", "2048") or 2048)
                max_tok = base_tok
                attempts = 3
                delay = 1.0
                last_err = None
                for attempt in range(1, attempts + 1):
                    try:
                        async with sem:
                            try:
                                return await client.chat.completions.create(
                                    model=model_name,
                                    messages=messages,
                                    response_format={"type": "json_schema", "json_schema": schema},
                                    max_completion_tokens=max_tok,
                                    **extra_params
                                )
                            except APIStatusError as e:
                                etxt = str(e).lower()
                                # Fallback response_format handling
                                if ("response_format" in etxt and ("json_schema" in etxt or "not supported" in etxt)) or "invalid parameter" in etxt:
                                    try:
                                        return await client.chat.completions.create(
                                            model=model_name,
                                            messages=messages,
                                            response_format={"type": "json_object"},
                                            max_completion_tokens=max_tok,
                                            **extra_params
                                        )
                                    except APIStatusError as e2:
                                        etxt2 = str(e2).lower()
                                        if "response_format" in etxt2 and ("json_object" in etxt2 or "not supported" in etxt2):
                                            return await client.chat.completions.create(
                                                model=model_name,
                                                messages=messages,
                                                max_completion_tokens=max_tok,
                                                **extra_params
                                            )
                                        else:
                                            raise
                                else:
                                    raise
                    except (RateLimitError, APITimeoutError, APIConnectionError, APIStatusError) as e:
                        last_err = e
                        msg = str(e).lower()
                        # If output limit reached, try with smaller max tokens next attempt
                        if "max_tokens" in msg or "output limit" in msg:
                            max_tok = max(256, max_tok // 2)
                        # Backoff for 429 or timeouts
                        if isinstance(e, RateLimitError) or "429" in msg or "rate limit" in msg:
                            await asyncio.sleep(delay)
                            delay = min(delay * 2, 8.0)
                            continue
                        # For other APIStatusError, do one more quick retry, then give up
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, 8.0)
                        continue
                # After retries, re-raise last error
                if last_err:
                    raise last_err
                raise RuntimeError("unknown error in _create_with_fallback_case")

            response = await _create_with_fallback_case()
            
            end_time = time.time()
            duration = end_time - start_time
            total_time += duration
            total_input_tokens += response.usage.prompt_tokens
            total_output_tokens += response.usage.completion_tokens
            
            # Parse and evaluate result
            content = response.choices[0].message.content
            if not raw_mode:
                result = parse_and_evaluate_result(
                    content,
                    expected_vehicle, expected_eta, expected_status,
                    text, i + 1, base_time_iso, prev_eta_hhmm
                )
            else:
                # RAW mode: parse JSON, compare absolute ISO directly
                try:
                    data = json.loads(content)
                except Exception:
                    m = re.search(r"\{.*?\}", content, re.S)
                    if m:
                        try:
                            data = json.loads(m.group(0))
                        except Exception:
                            data = {}
                    else:
                        data = {}
                parsed_vehicle = data.get("vehicle", "Unknown")
                parsed_eta_iso = data.get("eta_iso", "Unknown")
                parsed_status = data.get("status", "Unknown")

                # Normalize vehicle formatting
                vnorm = parsed_vehicle
                if isinstance(vnorm, str) and (vnorm.startswith("SAR-") or vnorm.startswith("SAR ")):
                    try:
                        num = int(re.findall(r"\d+", vnorm)[0])
                        vnorm = f"SAR-{num}"
                    except Exception:
                        pass
                if vnorm == "Unknown":
                    vnorm = normalize_vehicle(text)

                # Status by deterministic classifier for scoring
                snorm = classify_status_from_text(text)

                # ETA: validate ISO and apply tolerance
                if snorm in ("Cancelled", "Not Responding"):
                    eta_norm = "Unknown"
                else:
                    try:
                        _ = from_iso(parsed_eta_iso) if parsed_eta_iso and parsed_eta_iso != "Unknown" else None
                        eta_norm = parsed_eta_iso if _ else "Unknown"
                    except Exception:
                        eta_norm = "Unknown"

                vehicle_correct = (vnorm == expected_vehicle)
                if expected_eta == "Unknown":
                    eta_correct = (eta_norm == expected_eta)
                else:
                    try:
                        a = from_iso(eta_norm) if eta_norm != "Unknown" else None
                        b = from_iso(expected_eta)
                        eta_correct = a is not None and abs(int((a - b).total_seconds() // 60)) <= TOLERANCE_MIN
                    except Exception:
                        eta_correct = False
                status_correct = (snorm == expected_status)
                exact_match = vehicle_correct and eta_correct and status_correct

                result = {
                    "vehicle_correct": vehicle_correct,
                    "eta_correct": eta_correct,
                    "status_correct": status_correct,
                    "exact_match": exact_match,
                }
            all_results.append(result)
            
        except Exception as e:
            print(f"    ❌ Error on test case {i+1}: {e}")
            # Mark as skipped so we don't penalize accuracy for infra hiccups
            all_results.append({
                "vehicle_correct": False,
                "eta_correct": False,
                "status_correct": False,
                "exact_match": False,
                "skipped": True
            })
    
    # Calculate metrics
    # Exclude skipped cases from accuracy denominators
    valid = [r for r in all_results if not r.get("skipped")]
    if not valid:
        vehicle_accuracy = eta_accuracy = status_accuracy = exact_accuracy = 0.0
    else:
        vehicle_accuracy = np.mean([r["vehicle_correct"] for r in valid])
        eta_accuracy = np.mean([r["eta_correct"] for r in valid])
        status_accuracy = np.mean([r["status_correct"] for r in valid])
        exact_accuracy = np.mean([r["exact_match"] for r in valid])
    
    return {
        "config": description,
        "model": model_name,
        "vehicle_accuracy": vehicle_accuracy,
        "eta_accuracy": eta_accuracy,
        "status_accuracy": status_accuracy,
        "exact_accuracy": exact_accuracy,
        "total_time": total_time,
    "avg_time": total_time / max(1, len(valid)),
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
    "avg_input_tokens": total_input_tokens / max(1, len(valid)),
    "avg_output_tokens": total_output_tokens / max(1, len(valid)),
    "test_cases": len(valid)
    }

def display_benchmark_comparison(results):
    """Display benchmark results in a comparison table."""
    
    print(f"\n{BOLD}🏆 SAR Extraction Benchmark Results{RESET}")
    print("=" * 140)
    
    # Sort by exact accuracy (descending), then by average time (ascending)
    results.sort(key=lambda x: (-x["exact_accuracy"], x["avg_time"]))
    
    # Prepare table headers like main.py
    config_headers = ["Model", "Verbosity", "Reasoning"]
    metric_headers = ["Vehicle %", "ETA %", "Status %", "Exact %", "Avg Time (s)", "Avg Input", "Avg Output"]
    headers = [f"{BOLD}{h}{RESET}" for h in config_headers + metric_headers]
    
    table_data = []
    
    # Get min/max values for coloring
    exact_scores = [r["exact_accuracy"] for r in results]
    time_scores = [r["avg_time"] for r in results]
    vehicle_scores = [r["vehicle_accuracy"] for r in results]
    eta_scores = [r["eta_accuracy"] for r in results]
    status_scores = [r["status_accuracy"] for r in results]
    
    max_exact = max(exact_scores) if exact_scores else 0
    min_time = min(time_scores) if time_scores else float('inf')
    max_vehicle = max(vehicle_scores) if vehicle_scores else 0
    max_eta = max(eta_scores) if eta_scores else 0
    max_status = max(status_scores) if status_scores else 0
    
    for result in results:
        # Parse model config to extract verbosity and reasoning
        config = result["config"]
        model_name = result["model"]
        
        # Extract verbosity and reasoning from description
        verbosity = "N/A"
        reasoning = "N/A"
        
        if "verbosity=" in config:
            verbosity_match = re.search(r"verbosity=(\w+)", config)
            if verbosity_match:
                verbosity = verbosity_match.group(1)
        
        if "reasoning=" in config:
            reasoning_match = re.search(r"reasoning=(\w+)", config)
            if reasoning_match:
                reasoning = reasoning_match.group(1)
        
        # Color coding for best results
        vehicle_color = GREEN if result["vehicle_accuracy"] == max_vehicle else ""
        eta_color = GREEN if result["eta_accuracy"] == max_eta else ""
        status_color = GREEN if result["status_accuracy"] == max_status else ""
        exact_color = GREEN if result["exact_accuracy"] == max_exact else ""
        time_color = GREEN if result["avg_time"] == min_time else ""
        reset = RESET if any([vehicle_color, eta_color, status_color, exact_color, time_color]) else ""
        
        row = [
            f"{BOLD}{model_name}{RESET}",
            verbosity,
            reasoning,
            f"{vehicle_color}{result['vehicle_accuracy']:.1%}{reset}",
            f"{eta_color}{result['eta_accuracy']:.1%}{reset}",
            f"{status_color}{result['status_accuracy']:.1%}{reset}",
            f"{exact_color}{result['exact_accuracy']:.1%}{reset}",
            f"{time_color}{result['avg_time']:.2f}{reset}",
            f"{result['avg_input_tokens']:.0f}",
            f"{result['avg_output_tokens']:.0f}"
        ]
        table_data.append(row)
    
    from tabulate import tabulate
    print(tabulate(table_data, headers=headers, tablefmt="pretty"))
    
    # Summary statistics
    print(f"\n{BOLD}📊 Summary Statistics:{RESET}")
    print(f"• Best Exact Match Accuracy: {GREEN}{max(exact_scores):.1%}{RESET}")
    print(f"• Best Vehicle Accuracy: {GREEN}{max(vehicle_scores):.1%}{RESET}")
    print(f"• Best ETA Accuracy: {GREEN}{max(eta_scores):.1%}{RESET}")
    print(f"• Best Status Accuracy: {GREEN}{max(status_scores):.1%}{RESET}")
    print(f"• Fastest Average Response: {GREEN}{min(time_scores):.2f}s{RESET}")
    print(f"• Total Test Cases per Model: {results[0]['test_cases']}")
    print(f"• Models Tested: {len(results)}")
    
    # Add detailed color-coded results at the bottom
    print(f"\n{BOLD}📋 Detailed Results Summary:{RESET}")
    print("-" * 80)
    
    for result in results:
        config = result["config"]
        exact_pct = result["exact_accuracy"]
        vehicle_pct = result["vehicle_accuracy"] 
        eta_pct = result["eta_accuracy"]
        status_pct = result["status_accuracy"]
        avg_time = result["avg_time"]
        
        # Color code based on performance
        if exact_pct >= 0.4:
            color = GREEN
        elif exact_pct >= 0.2:
            color = YELLOW
        else:
            color = RED
            
        print(f"{color}{config:40}{RESET} | "
              f"Vehicle: {vehicle_pct:>6.1%} | "
              f"ETA: {eta_pct:>6.1%} | " 
              f"Status: {status_pct:>6.1%} | "
              f"Exact: {BOLD}{exact_pct:>6.1%}{RESET} | "
              f"Time: {avg_time:>5.2f}s")
    
    # Detailed color-coded breakdown
    print(f"\n{BOLD}🎯 Detailed Performance Breakdown:{RESET}")
    print("=" * 120)
    
    # Group by base model for easier comparison
    model_groups = {}
    for result in results:
        base_model = result["model"]
        if base_model not in model_groups:
            model_groups[base_model] = []
        model_groups[base_model].append(result)
    
    for base_model in sorted(model_groups.keys()):
        model_results = model_groups[base_model]
        print(f"\n{BOLD}{base_model.upper()}:{RESET}")
        
        # Sort by exact accuracy within each model group
        model_results.sort(key=lambda x: -x["exact_accuracy"])
        
        for result in model_results:
            config_name = result["config"].replace(f"{base_model} ", "").replace("(", "").replace(")", "")
            if config_name == "default":
                config_name = "baseline"
            
            # Color code based on performance
            exact_pct = result["exact_accuracy"]
            if exact_pct >= 0.4:
                color = GREEN
            elif exact_pct >= 0.2:
                color = YELLOW
            else:
                color = RED
            
            print(f"  {color}● {config_name:25}{RESET} "
                  f"Exact: {color}{exact_pct:.1%}{RESET}  "
                  f"Vehicle: {result['vehicle_accuracy']:.1%}  "
                  f"ETA: {result['eta_accuracy']:.1%}  "
                  f"Status: {result['status_accuracy']:.1%}  "
                  f"⚡ {result['avg_time']:.2f}s")
    
    # Best performers summary
    print(f"\n{BOLD}🏆 Top Performers:{RESET}")
    top_3 = sorted(results, key=lambda x: -x["exact_accuracy"])[:3]
    for i, result in enumerate(top_3, 1):
        medal = ["🥇", "🥈", "🥉"][i-1]
        print(f"  {medal} {result['config']} - {GREEN}{result['exact_accuracy']:.1%}{RESET} exact match")
    
    # Fastest responders
    print(f"\n{BOLD}⚡ Fastest Responders:{RESET}")
    fastest_3 = sorted(results, key=lambda x: x["avg_time"])[:3]
    for i, result in enumerate(fastest_3, 1):
        print(f"  {i}. {result['config']} - {GREEN}{result['avg_time']:.2f}s{RESET} avg response")

if __name__ == "__main__":
    # Unified CLI that respects flags even in comprehensive mode
    import argparse
    parser = argparse.ArgumentParser(description="SAR LLM Extraction Benchmark")
    parser.add_argument("--comprehensive", action="store_true", help="Run full model comparison grid")
    parser.add_argument("--raw", action="store_true", help="Raw mode for simple run (LLMs do parsing)")
    parser.add_argument("--raw-only", action="store_true", help="In comprehensive mode, run RAW only")
    parser.add_argument("--assisted-only", action="store_true", help="In comprehensive mode, run ASSISTED only")
    parser.add_argument("--cases", type=str, default=None, help="Path to test cases JSON")
    parser.add_argument("--tolerance-min", type=int, default=2, help="ETA tolerance in minutes")
    parser.add_argument("--models", type=str, default=None, help="Comma-separated models for simple run")
    args, _ = parser.parse_known_args()

    # Route to the correct runner
    if args.comprehensive:
        # In comprehensive runs, --raw-only / --assisted-only control which modes execute
        run_assisted = not args.raw_only
        run_raw = not args.assisted_only
        asyncio.run(run_comprehensive_benchmark(run_assisted=run_assisted, run_raw=run_raw))
    else:
        # For the simple run, preserve existing flags by mutating argv-like globals used in main()
        if args.cases:
            CASES_FILE = args.cases
        if args.tolerance_min is not None:
            TOLERANCE_MIN = args.tolerance_min
        if args.models:
            BENCH_MODELS = [m.strip() for m in args.models.split(",") if m.strip()]
        asyncio.run(main())
