#!/usr/bin/env python3
"""
Mission Simulator for Respondr Lite (Supercharged)

- Uses an LLM to plan each mission: cast + timeline as strict JSON
- Mixed cast assembled from supported SAR groups (IDs below)
- Randomizes team size (defaults 10–40) and message window (defaults 30–60 minutes)
- Feeds messages over time into a single mission GroupMe thread
- Keepalive runs during the active window to simulate a dashboard being viewed
- Runs continuously: executes a mission every ~48 hours (with --force-mission to start now)
- Supports OpenAI or Azure OpenAI automatically
- Time acceleration (--speed) for dev/test (affects in-mission timing only)

Usage:
    python mission_simulator.py [--dry-run] [--force-mission] [--speed 2.0]
                                [--min-team 10] [--max-team 40]
                                [--min-window 30] [--max-window 60]
"""

import json
import random
import time
import requests
import logging
import math
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
import argparse
import os
import re
from dotenv import load_dotenv

# OpenAI / Azure OpenAI clients
try:
    from openai import OpenAI, AzureOpenAI
except Exception:
    OpenAI = None
    AzureOpenAI = None

# Azure Table Storage client
try:
    from azure.data.tables import TableServiceClient
except Exception:
    TableServiceClient = None

# Load environment variables
load_dotenv()

# -----------------------------------------------------------
# Logging
# -----------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("mission-simulator")

# -----------------------------------------------------------
# Configuration: Real SAR Team Group IDs (as provided)
# -----------------------------------------------------------
REAL_GROUP_IDS: Dict[str, str] = {
    "97608845": "4X4",
    "6846970": "ASAR",
    "61402638": "ASAR",
    "19723040": "SSAR",
    "96018206": "IMT",
    "1596896": "K9",
    "92390332": "ASAR",
    "99606944": "OSU",
    "14533239": "MSAR",
    "106549466": "ESAR",
    "16649586": "OSU",
    "19801892": "Tracker",
}

AZURE_FUNCTION_ENDPOINT = os.getenv("AZURE_FUNCTION_ENDPOINT", "https://respondrliteapp-d5614dea.azurewebsites.net")
WEBHOOK_API_KEY = os.getenv("WEBHOOK_API_KEY")
PREPROD_WEB_ENDPOINT = os.getenv("PREPROD_WEB_ENDPOINT", "https://preprod.scvsar.app")

# Authentication for keepalive (optional)
LOCAL_USER_NAME = os.getenv("LOCAL_USER_NAME")
LOCAL_USER_PASSWORD = os.getenv("LOCAL_USER_PASSWORD")

# OpenAI / Azure OpenAI env
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5-nano")  # if using Azure

# --- Model defaults (OpenAI preferred, Azure fallback) ---
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-5")  # Use GPT-5 with reasoning
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "gpt-5-mini")
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "medium")  # minimal|low|medium|high
LLM_VERBOSITY = os.getenv("LLM_VERBOSITY", "medium")               # low|medium|high

# Azure Storage configuration
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT")
# Use the same table as the main app to keep analysis in sync
STORAGE_TABLE_NAME = "ResponderMessages"
logger.info(f"Using table: {STORAGE_TABLE_NAME}")


# -----------------------------------------------------------
# Data classes
# -----------------------------------------------------------
@dataclass
class MissionLocation:
    name: str
    coordinates: Tuple[float, float]  # (lat, lon)
    trail_description: str
    typical_scenarios: List[str]

@dataclass
class Responder:
    name: str
    user_id: str
    sender_id: str
    experience_level: str  # "rookie", "experienced", "veteran"
    response_probability: float
    vehicle_preference: str  # "POV", "SAR-X", "SAR Rig" (e.g., SAR-12)
    personality: str  # "precise", "casual", "talkative", "quiet"
    # The group thread we send into for THIS mission (single GroupMe thread per mission)
    mission_group_id: str = "6846970"
    # The responder's "home" group (persona attribute; not used for posting target)
    home_group_id: Optional[str] = None

@dataclass
class PlannedMessage:
    sender_index: int
    type: str  # "initial_response" | "followup" | "status" | "cancellation"
    text: str
    offset_sec: float

# -----------------------------------------------------------
# Utilities
# -----------------------------------------------------------
def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def rand_group_id(exclude: Optional[str] = None) -> str:
    keys = list(REAL_GROUP_IDS.keys())
    if exclude and exclude in keys and len(keys) > 1:
        keys.remove(exclude)
    return random.choice(keys)

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def clamp(x: float, a: float, b: float) -> float:
    return max(a, min(b, x))

def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """
    Try very hard to pull a single JSON object out of the text.
    Handles code fences and stray commentary if model didn't obey JSON-only.
    """
    if not text:
        return None
    # Strip code fences
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE | re.MULTILINE)
    # Find first '{' and last '}' to isolate a JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Try to repair common issues (dangling trailing commas)
            candidate2 = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                return json.loads(candidate2)
            except Exception:
                return None
    return None

# -----------------------------------------------------------
# LLM Planning
# -----------------------------------------------------------
class LLMPlanner:
    """
    Produces a mission plan (cast + timeline) using GPT‑5 with:
    - reasoning_effort="medium"
    - verbosity="medium"
    - Structured Outputs (JSON Schema, strict)
    Falls back progressively if features aren't available.
    """

    def __init__(self):
        self.client = None
        self.using_azure = False
        self.model_primary = LLM_MODEL
        self.model_fallback = LLM_FALLBACK_MODEL
        self.reasoning_effort = LLM_REASONING_EFFORT
        self.verbosity = LLM_VERBOSITY

        # Prefer Azure OpenAI if configured (since we are migrating), otherwise OpenAI
        if AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT and AzureOpenAI:
            try:
                self.client = AzureOpenAI(
                    api_key=AZURE_OPENAI_API_KEY,
                    api_version="2024-12-01-preview",
                    azure_endpoint=AZURE_OPENAI_ENDPOINT,
                )
                self.using_azure = True
                self.model_primary = AZURE_OPENAI_DEPLOYMENT
                self.model_fallback = AZURE_OPENAI_DEPLOYMENT
                logger.info(f"Azure OpenAI client initialized with deployment: {AZURE_OPENAI_DEPLOYMENT}")
            except Exception as e:
                logger.warning(f"Failed to init Azure OpenAI client: {e}")

        # Fallback to OpenAI if Azure not used/failed
        if not self.client and OPENAI_API_KEY and OpenAI:
            try:
                self.client = OpenAI(api_key=OPENAI_API_KEY)
                logger.info("OpenAI client initialized.")
            except Exception as e:
                logger.warning(f"Failed to init OpenAI client: {e}")

        if not self.client:
            logger.warning("No LLM client available. Will fall back to template plan.")

    def available(self) -> bool:
        return self.client is not None

    # ---- Build a strict JSON Schema for the mission plan ----
    def _mission_schema(self, min_team: int, max_team: int,
                        min_window_min: int, max_window_min: int) -> dict:
        home_id_enum = list(REAL_GROUP_IDS.keys())
        return {
            "type": "object",
            "properties": {
                "team": {
                    "type": "array",
                    "minItems": min_team,
                    "maxItems": max_team,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["name", "experience_level", "personality", "vehicle_preference", "home_group_id"],
                        "properties": {
                            "name": {"type": "string", "minLength": 3, "maxLength": 60},
                            "experience_level": {"type": "string", "enum": ["rookie", "experienced", "veteran"]},
                            "personality": {"type": "string", "enum": ["precise", "casual", "talkative", "quiet"]},
                            "vehicle_preference": {
                                "type": "string",
                                "pattern": r"^(POV|SAR-(?:[1-9][0-9]?)|SAR Rig)$"
                            },
                            "home_group_id": {"type": "string", "enum": home_id_enum}
                        }
                    }
                },
                "messages": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["sender_index", "type", "text", "offset_sec"],
                        "properties": {
                            "sender_index": {"type": "integer", "minimum": 0},
                            "type": {"type": "string", "enum": ["initial_response", "followup", "status", "cancellation"]},
                            "text": {"type": "string", "minLength": 2, "maxLength": 140},
                            "offset_sec": {"type": "number", "minimum": 0}
                        }
                    }
                },
                "window_minutes": {
                    "type": "integer",
                    "minimum": min_window_min,
                    "maximum": max_window_min
                }
            },
            "required": ["team", "messages", "window_minutes"],
            "additionalProperties": False
        }

    def _chat_with_schema(self, *, model: str, system: str, user: str, schema: dict,
                          max_tokens: int = 50000) -> Optional[Dict[str, Any]]:
        """
        Try strict JSON Schema → JSON object → freeform+extract, stripping unsupported params on retry.
        """
        def try_call(use_schema=True, include_new_params=True, json_object=False):
            kwargs = {
                "model": model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            }
            
            # GPT-5 models use max_completion_tokens instead of max_tokens and only support default temperature
            if model.startswith("gpt-5"):
                kwargs["max_completion_tokens"] = max_tokens
                # GPT-5 only supports default temperature (1.0), so don't set it
            else:
                kwargs["max_tokens"] = max_tokens
                kwargs["temperature"] = 0.6
            
            # Azure OpenAI specific adjustments
            if self.using_azure:
                # Azure doesn't support max_tokens for o1/gpt-5 models, ensure we use max_completion_tokens
                if "max_tokens" in kwargs:
                    del kwargs["max_tokens"]
                    kwargs["max_completion_tokens"] = max_tokens
                
                # Azure doesn't support temperature for o1/gpt-5 models
                if "temperature" in kwargs and (model.startswith("gpt-5") or model.startswith("o1")):
                    del kwargs["temperature"]
            if include_new_params and not self.using_azure:
                # GPT‑5 params only work with OpenAI, not Azure OpenAI currently
                kwargs["reasoning_effort"] = self.reasoning_effort
                kwargs["verbosity"] = self.verbosity
            if use_schema:
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "mission_plan", "schema": schema, "strict": True},
                }
            elif json_object:
                kwargs["response_format"] = {"type": "json_object"}

            logger.info(f"Calling LLM with model={model}, use_schema={use_schema}, json_object={json_object}")
            start_ts = time.time()
            try:
                resp = self.client.chat.completions.create(**kwargs)
                duration = time.time() - start_ts
                logger.info(f"LLM call returned in {duration:.2f}s")
                return resp
            except Exception as e:
                duration = time.time() - start_ts
                logger.warning(f"LLM call failed after {duration:.2f}s: {e}")
                raise e

        # Strategy: Simplified for Azure gpt-5-nano deployment
        if self.using_azure:
            # Azure gpt-5-nano may not support advanced features - use simpler approach
            tries = [
                {"use_schema": False, "include_new_params": False, "json_object": True },
                {"use_schema": False, "include_new_params": False, "json_object": False},
            ]
        else:
            # Full strategy for OpenAI
            tries = [
                {"use_schema": True,  "include_new_params": True,  "json_object": False},
                {"use_schema": True,  "include_new_params": False, "json_object": False},
                {"use_schema": False, "include_new_params": True,  "json_object": True },
                {"use_schema": False, "include_new_params": False, "json_object": True },
                {"use_schema": False, "include_new_params": False, "json_object": False},
            ]

        for i, t in enumerate(tries):
            try:
                resp = try_call(**t)
                
                # Debug logging for OpenAI responses
                logger.info(f"OpenAI API Response (strategy {i+1}/5):")
                logger.info(f"  Model: {model}")
                logger.info(f"  Response ID: {getattr(resp, 'id', 'N/A')}")
                logger.info(f"  Usage: {getattr(resp, 'usage', 'N/A')}")
                logger.info(f"  Choices count: {len(resp.choices) if resp.choices else 0}")
                
                if resp.choices and len(resp.choices) > 0:
                    choice = resp.choices[0]
                    logger.info(f"  Finish reason: {getattr(choice, 'finish_reason', 'N/A')}")
                    content = choice.message.content
                    logger.info(f"  Content length: {len(content) if content else 0}")
                    logger.info(f"  Content preview: {content[:200] if content else 'None'}...")
                    
                    obj = extract_json_object(content)
                    if obj:
                        logger.info(f"  JSON extraction: SUCCESS")
                        if i > 0:  # Log if we had to fallback
                            logger.info(f"LLM call succeeded using strategy {i+1}/5")
                        return obj
                    else:
                        logger.warning(f"  JSON extraction: FAILED - could not parse JSON from content")
                        logger.warning(f"  Full content: {content}")
                else:
                    logger.warning(f"  No choices in response")
                    
            except Exception as e:
                # If Azure or older backends reject unknown params, just continue to the next strategy
                error_msg = str(e).lower()
                logger.warning(f"LLM call failed (strategy {i+1}/5): {e}")
                logger.warning(f"  Exception type: {type(e).__name__}")
                if "bad request" in error_msg or "invalid" in error_msg:
                    logger.warning(f"  Likely parameter compatibility issue")
                continue
        
        logger.error("All LLM call strategies failed, falling back to template plan")
        return None

    def plan_mission(
        self,
        mission_group_id: str,
        location: MissionLocation,
        start_time_utc: datetime,
        min_team: int,
        max_team: int,
        min_window_min: int,
        max_window_min: int,
    ) -> Optional[Dict[str, Any]]:
        if not self.available():
            return None

        start_iso = start_time_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        group_map = json.dumps(REAL_GROUP_IDS, indent=0)
        system = (
            "You are a SAR communications planner. Produce ONLY a JSON object that simulates a realistic "
            "mission response thread for a single incident. Use terse, authentic SAR tone."
        )
        user = f"""
Plan a mission response:
- Mission group thread id: {mission_group_id}
- Start time (UTC): {start_iso}
- Location: {location.name} ({location.coordinates[0]:.4f},{location.coordinates[1]:.4f}) — {location.trail_description}
- Typical scenarios: {", ".join(location.typical_scenarios)}
- Supported SAR groups/ids: {group_map}

Constraints:
- Team size N with {min_team} ≤ N ≤ {max_team}
- Window W minutes with {min_window_min} ≤ W ≤ {max_window_min}
- At least 3 distinct home_group_id values across the team
- Front-load initial responses (<15 min), 5–15% cancellations, 20–35% follow-ups/status later
- Each message < 20 words, no real phone numbers

Output format (STRICT):
{{
    "team": [
        {{"name": "...", "experience_level": "rookie", "personality": "precise", "vehicle_preference": "POV", "home_group_id": "6846970"}}
    ],
    "messages": [
        {{"sender_index": 0, "type": "initial_response", "text": "Responding POV ETA 25", "offset_sec": 120}}
    ],
    "window_minutes": 45
}}

Requirements for the JSON you return:
- The value of "team" MUST be an array with one object per responder (never an object/dictionary).
- The value of "messages" MUST be an array with one object per message.
- Every responder object MUST include: name, experience_level, personality, vehicle_preference, home_group_id.
- Every message object MUST include: sender_index, type, text, offset_sec. Indices refer to the team array.
- Provide only valid JSON with double quotes and no commentary or markdown fences.
"""
        schema = self._mission_schema(min_team, max_team, min_window_min, max_window_min)

        # Try primary then fallback model with the strategy above
        for model in [self.model_primary, self.model_fallback]:
            plan = self._chat_with_schema(model=model, system=system, user=user, schema=schema, max_tokens=50000)
            if plan:
                return plan
        return None

    def analyze_mission_performance(
        self,
        mission_data: Dict[str, Any],
        responder_results: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze how well the LLM performed in parsing messages and applying common sense.
        Returns a structured analysis with message grading.
        """
        if not self.available():
            return None

        system = (
            "You are a SAR mission analyst. Analyze how well the system parsed and interpreted "
            "SAR communication messages. Grade each message and provide comprehensive analysis. "
            "Produce ONLY a JSON object with your analysis."
        )

        user = f"""
Analyze this SAR mission performance:

MISSION DATA:
{json.dumps(mission_data, indent=2)}

RESPONDER RESULTS FROM /api/responders:
{json.dumps(responder_results, indent=2)}

Provide a comprehensive analysis including:
1. Overall parsing accuracy
2. Common sense interpretation quality  
3. Message-by-message grading (A-F scale)
4. Identification of parsing errors or misinterpretations
5. Recommendations for improvement

Format as JSON with this structure:
{{
  "overall_score": "A-F grade",
  "parsing_accuracy": "percentage or description",
  "interpretation_quality": "assessment",
  "message_grades": [
    {{
      "message_index": 0,
      "message_text": "original message",
      "sender": "sender name",
      "grade": "A-F",
      "parsing_quality": "assessment",
      "interpretation_notes": "detailed analysis",
      "errors_found": ["list of errors if any"]
    }}
  ],
  "summary": {{
    "strengths": ["list of strengths"],
    "weaknesses": ["list of weaknesses"],
    "recommendations": ["list of recommendations"]
  }}
}}
"""

        # Use a simpler approach for analysis - no complex schema needed
        for model in [self.model_primary, self.model_fallback]:
            try:
                kwargs = {
                    "model": model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "response_format": {"type": "json_object"}
                }
                
                # Handle model-specific parameters
                if model.startswith("gpt-5"):
                    kwargs["max_completion_tokens"] = 50000
                else:
                    kwargs["max_tokens"] = 50000
                    kwargs["temperature"] = 0.7

                resp = self.client.chat.completions.create(**kwargs)
                content = resp.choices[0].message.content
                analysis = extract_json_object(content)
                if analysis:
                    return analysis
            except Exception as e:
                logger.warning(f"Mission analysis failed with model {model}: {e}")
                continue
        
        logger.error("Mission analysis failed for all models")
        return None


# -----------------------------------------------------------
# Simulator
# -----------------------------------------------------------
class MissionSimulator:
    def __init__(self, dry_run: bool = False, speed: float = 1.0,
                 min_team: int = 10, max_team: int = 40,
                 min_window_min: int = 30, max_window_min: int = 60,
                 group_mode: str = "single"):
        self.dry_run = dry_run
        self.speed = max(0.1, float(speed))  # prevent zero/negative
        self.min_team = min_team
        self.max_team = max_team
        self.min_window_min = min_window_min
        self.max_window_min = max_window_min
        self.group_mode = group_mode  # store routing mode

        # LLM planner
        self.planner = LLMPlanner()

        # Mission tracking
        self.keepalive_stop_event = threading.Event()
        self.auth_token = None

    # ---------------- Locations ----------------
    @property
    def snohomish_locations(self) -> List[MissionLocation]:
        return [
            MissionLocation("Lake 22 Trail", (48.0767, -121.7843), "2.7 mile trail to alpine lake",
                            ["injured hiker", "lost hiker", "medical emergency", "hypothermia"]),
            MissionLocation("Lake Serene Trail", (47.8165, -121.5789), "4.5 mile trail with waterfall views",
                            ["slip and fall", "cardiac event", "lost party", "stuck climber"]),
            MissionLocation("Wallace Falls", (47.8710, -121.6776), "Popular waterfall hike",
                            ["ankle injury", "heat exhaustion", "lost child", "dog rescue"]),
            MissionLocation("Heather Lake", (48.0589, -121.7935), "1.5 mile hike to subalpine lake",
                            ["severe laceration", "broken bone", "altitude sickness", "stuck hiker"]),
            MissionLocation("Mount Pilchuck", (48.0709, -121.8165), "Steep 3-mile trail to fire lookout",
                            ["fall from rocks", "weather exposure", "lost in fog", "equipment failure"]),
            MissionLocation("Gothic Basin", (48.0845, -121.4367), "Challenging backcountry access",
                            ["rockfall injury", "stream crossing accident", "overnight rescue", "weather emergency"]),
        ]

    # ---------------- Auth (optional) ----------------
    def _authenticate(self) -> bool:
        if not LOCAL_USER_NAME or not LOCAL_USER_PASSWORD:
            return False
        if self.dry_run:
            self.auth_token = "dry-run-token"
            return True
        try:
            r = requests.post(
                f"{PREPROD_WEB_ENDPOINT}/api/auth/local/login",
                json={"username": LOCAL_USER_NAME, "password": LOCAL_USER_PASSWORD},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("success") and data.get("token"):
                    self.auth_token = data["token"]
                    logger.info("Authenticated for keepalive pings.")
                    return True
        except Exception as e:
            logger.debug(f"Auth error: {e}")
        return False

    # ---------------- Keepalive ----------------
    def start_website_keepalive(self, expected_minutes: int):
        """
        Keep the site warm roughly for the mission window + small buffer.
        Ping every 2–3 minutes with jitter, or faster when --speed accelerates.
        """
        # Reset/clear old event
        self.keepalive_stop_event = threading.Event()

        def worker():
            max_duration = int((expected_minutes + 10) * 60 / self.speed)
            start = time.time()
            logger.info(f"Starting website keepalive for ~{expected_minutes+10} min (scaled by speed).")
            while not self.keepalive_stop_event.is_set():
                if time.time() - start >= max_duration:
                    break
                try:
                    if self.dry_run:
                        logger.info("[KEEPALIVE DRY RUN] GET /api/storage-info")
                    else:
                        headers = {"User-Agent": "Mission-Simulator-Keepalive/1.1"}
                        if self.auth_token:
                            headers["Authorization"] = f"Bearer {self.auth_token}"
                        resp = requests.get(f"{PREPROD_WEB_ENDPOINT}/api/storage-info", timeout=20, headers=headers)
                        if resp.status_code == 200:
                            logger.info("✓ Keepalive ping ok")
                        else:
                            logger.warning(f"Keepalive non-200: {resp.status_code}")
                except Exception as e:
                    logger.debug(f"Keepalive ping failed: {e}")
                # sleep 2–3 real minutes, scaled by speed (min 10s)
                wait = random.uniform(120, 180) / self.speed
                time.sleep(max(10, wait))
            logger.info("Website keepalive stopped.")

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        return t

    def stop_website_keepalive(self):
        self.keepalive_stop_event.set()

    # ---------------- Messaging ----------------
    def _random_guid(self) -> str:
        # Source GUID shape
        return f"{random.randint(10000000, 99999999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}-{random.randint(100000000000, 999999999999)}"

    def _random_avatar_url(self) -> str:
        return f"https://i.groupme.com/{random.randint(100, 999)}x{random.randint(100, 999)}.jpeg.{random.randint(10000000, 99999999)}"

    def send_message(self, group_id: str, name: str, sender_id: str, user_id: str, text: str) -> bool:
        if self.dry_run:
            logger.info(f"[DRY RUN] ({group_id}) {name}: {text}")
            return True
        if not WEBHOOK_API_KEY:
            logger.error("WEBHOOK_API_KEY not configured; set in .env")
            return False

        payload = {
            "attachments": [],
            "avatar_url": self._random_avatar_url(),
            "created_at": int(time.time()),
            "group_id": group_id,
            "id": str(random.randint(10**17, 10**18 - 1)),
            "name": name,
            "sender_id": sender_id,
            "sender_type": "user",
            "source_guid": self._random_guid(),
            "system": False,
            "text": text,
            "user_id": user_id,
        }
        try:
            r = requests.post(
                f"{AZURE_FUNCTION_ENDPOINT}/api/groupme_ingest?code={WEBHOOK_API_KEY}",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=12,
            )
            r.raise_for_status()
            logger.info(f"✓ {name}: {text}")
            return True
        except Exception as e:
            logger.error(f"Failed to send message from {name}: {e}")
            return False

    # ---------------- Helpers ----------------
    def _select_mission_group(self) -> str:
        gid = random.choice(list(REAL_GROUP_IDS.keys()))
        logger.info(f"Selected mission group: {REAL_GROUP_IDS[gid]} (ID: {gid})")
        return gid

    def _route_group_id(self, sender: Responder, msg_type: str, mission_group_id: str) -> str:
        """
        Decide which GroupMe group receives this message, based on routing mode.
        - single: everything to mission_group_id
        - multi: everything to the sender's home_group_id (fallback to mission thread)
        - split: initial_response to home_group_id; followup/status/cancellation to mission thread
        """
        mode = (self.group_mode or "single").lower()
        if mode == "single":
            return mission_group_id
        if mode == "multi":
            return sender.home_group_id or mission_group_id
        # split
        if msg_type == "initial_response":
            return sender.home_group_id or mission_group_id
        return mission_group_id

    def _send_initial_alerts(self, ic: Responder, alert_text: str,
                             team: List[Responder], mission_group_id: str) -> None:
        """
        Send the IC alert to the appropriate groups based on routing mode.
        - single: only the central mission thread
        - multi: broadcast to each unique home group
        - split: broadcast to each unique home group AND the mission thread (deduped)
        """
        mode = (self.group_mode or "single").lower()
        if mode == "single":
            self.send_message(mission_group_id, ic.name, ic.sender_id, ic.user_id, alert_text)
            return

        # Collect unique home groups from the team
        unique_home_groups = sorted({r.home_group_id for r in team if r.home_group_id})
        if mode == "multi":
            logger.info(f"Multi-group mode: broadcasting alert to {len(unique_home_groups)} home groups.")
            for gid in unique_home_groups:
                self.send_message(gid, ic.name, ic.sender_id, ic.user_id, alert_text)
        else:  # split
            logger.info(f"Split mode: broadcasting alert to {len(unique_home_groups)} home groups + mission thread.")
            sent_to = set()
            for gid in unique_home_groups:
                if gid:
                    if self.send_message(gid, ic.name, ic.sender_id, ic.user_id, alert_text):
                        sent_to.add(gid)
            # Also send to mission thread, if not already covered
            if mission_group_id not in sent_to:
                self.send_message(mission_group_id, ic.name, ic.sender_id, ic.user_id, alert_text)

    def generate_mission_alert(self, location: MissionLocation) -> str:
        scenario = random.choice(location.typical_scenarios)
        age = random.randint(18, 75)
        gender = random.choice(["M", "F"])
        injury_details = {
            "injured hiker": ["ankle fracture", "leg laceration", "head trauma", "back injury"],
            "lost hiker": ["disoriented", "hypothermic", "dehydrated", "phone dead"],
            "medical emergency": ["cardiac event", "diabetic emergency", "seizure", "allergic reaction"],
            "slip and fall": ["broken wrist", "concussion", "shoulder dislocation", "multiple lacerations"],
            "severe laceration": ["deep cut", "arterial bleeding", "needs sutures", "on blood thinners"],
            "broken bone": ["compound fracture", "cannot bear weight", "severe pain", "possible internal bleeding"],
        }
        detail = random.choice(injury_details.get(scenario, ["injured", "needs assistance"]))
        ic_phone = f"425{random.randint(1000000, 9999999)}"
        mission_type = random.choice(["PACKOUT", "TRANSPORT", "SEARCH", "RESCUE"])
        alert = (
            f"{mission_type} {location.name.upper()}. {age}Y{gender} {detail.upper()} "
            f"{random.choice(['CANT WALK', 'NEEDS IMMEDIATE EVAC', 'UNABLE TO CONTINUE', 'REQUIRES ASSISTANCE'])}. "
            f"{location.trail_description.upper()}. SAR{random.randint(1, 15)} IC {ic_phone}. "
            f"{location.coordinates[0]:.4f},{location.coordinates[1]:.4f}."
        )
        return alert

    def _assign_ids(self, n: int) -> List[Tuple[str, str]]:
        ids = []
        used = set()
        for _ in range(n):
            while True:
                uid = str(random.randint(100000000, 999999999))
                sid = str(random.randint(100000000, 999999999))
                if (uid, sid) not in used:
                    used.add((uid, sid))
                    ids.append((uid, sid))
                    break
        return ids

    def _validate_and_materialize_plan(
        self,
        raw: Dict[str, Any],
        mission_group_id: str,
        window_bounds: Tuple[int, int],
    ) -> Tuple[List[Responder], List[PlannedMessage], int]:
        """
        Enforce schema & constraints; fill IDs; clamp times; guarantee ≥3 unique home groups.
        Returns (team, messages, window_minutes).
        """
        min_window, max_window = window_bounds
        team_raw = raw.get("team") if isinstance(raw, dict) else []
        if isinstance(team_raw, dict):
            if isinstance(team_raw.get("members"), list):
                team_raw = team_raw.get("members")
            else:
                # Some models return a dictionary keyed by index; attempt to coerce to list
                try:
                    team_raw = list(team_raw.values())
                except Exception:
                    team_raw = []
        if not isinstance(team_raw, list):
            logger.warning("LLM plan provided non-list team; forcing fallback")
            team_raw = []

        msgs_raw = raw.get("messages") if isinstance(raw, dict) else []
        if isinstance(msgs_raw, dict):
            if isinstance(msgs_raw.get("items"), list):
                msgs_raw = msgs_raw.get("items")
            else:
                try:
                    msgs_raw = list(msgs_raw.values())
                except Exception:
                    msgs_raw = []
        if not isinstance(msgs_raw, list):
            logger.warning("LLM plan provided non-list messages; forcing fallback")
            msgs_raw = []
        window_minutes = raw.get("window_minutes") or random.randint(min_window, max_window)
        window_minutes = int(clamp(int(window_minutes), min_window, max_window))

        # Materialize team
        team: List[Responder] = []
        ids = self._assign_ids(len(team_raw))
        uniq_groups = set()
        for i, t in enumerate(team_raw):
            if not isinstance(t, dict):
                continue
            name = (t.get("name") or "Responder").strip()
            exp = t.get("experience_level") or random.choice(["rookie", "experienced", "veteran"])
            pers = t.get("personality") or random.choice(["precise", "casual", "talkative", "quiet"])
            veh = t.get("vehicle_preference") or random.choice(["POV", f"SAR-{random.randint(1,99)}", "SAR Rig"])
            home_gid = t.get("home_group_id") or rand_group_id()
            if home_gid not in REAL_GROUP_IDS:
                home_gid = rand_group_id()
            uniq_groups.add(home_gid)

            user_id, sender_id = ids[i]
            # Response probability map, jittered
            prob_map = {"rookie": 0.45, "experienced": 0.7, "veteran": 0.88}
            rp = clamp(prob_map.get(exp, 0.6) + random.uniform(-0.08, 0.08), 0.2, 0.95)

            team.append(
                Responder(
                    name=name,
                    user_id=user_id,
                    sender_id=sender_id,
                    experience_level=exp,
                    response_probability=rp,
                    vehicle_preference=veh,
                    personality=pers,
                    mission_group_id=mission_group_id,
                    home_group_id=home_gid,
                )
            )

        # Ensure at least 3 distinct home groups
        if len(uniq_groups) < 3 and team:
            while len(uniq_groups) < 3:
                idx = random.randrange(len(team))
                new_gid = rand_group_id(exclude=team[idx].home_group_id)
                team[idx].home_group_id = new_gid
                uniq_groups.add(new_gid)

        # Materialize messages (validated)
        messages: List[PlannedMessage] = []
        for m in msgs_raw:
            if not isinstance(m, dict):
                continue
            try:
                sender_index = int(m.get("sender_index", 0))
                if not (0 <= sender_index < len(team)):
                    continue
                mtype = (m.get("type") or "initial_response").strip()
                if mtype not in {"initial_response", "followup", "status", "cancellation"}:
                    mtype = "status"
                text = (m.get("text") or "").strip()
                if not text:
                    continue
                offset_sec = float(m.get("offset_sec", 0.0))
                offset_sec = clamp(offset_sec, 0, window_minutes * 60)
                messages.append(PlannedMessage(sender_index, mtype, text, offset_sec))
            except Exception:
                continue

        # Sort by offset
        messages.sort(key=lambda x: x.offset_sec)
        return team, messages, window_minutes

    # ---------------- Post-mission analysis ----------------
    def _fetch_responder_results_from_storage(self, mission_group_id: str, start_time: datetime) -> Optional[Dict[str, Any]]:
        """
        Fetch responder results directly from Azure Table Storage for post-mission analysis.
        """
        if self.dry_run:
            logger.info("[DRY RUN] Would fetch responder results from Azure Table Storage")
            # Return mock data for dry run
            return {
                "responders": [
                    {"name": "Mock Responder", "status": "responded", "messages": 3, "message_texts": ["Responding POV", "At TH", "Heading up"]},
                    {"name": "Another Responder", "status": "cancelled", "messages": 1, "message_texts": ["Can't make it"]}
                ],
                "total_messages": 4,
                "response_rate": 0.75,
                "mission_group_id": mission_group_id,
                "time_range": {
                    "start": start_time.isoformat(),
                    "end": now_utc().isoformat()
                }
            }
        
        if not AZURE_STORAGE_CONNECTION_STRING or not TableServiceClient:
            logger.warning("Azure Storage not configured or SDK not available, using mock data")
            # Return mock data directly instead of recursive call
            return {
                "responders": [
                    {"name": "Mock Responder", "status": "responded", "messages": 3, "message_texts": ["Responding POV", "At TH", "Heading up"]},
                    {"name": "Another Responder", "status": "cancelled", "messages": 1, "message_texts": ["Can't make it"]}
                ],
                "total_messages": 4,
                "response_rate": 0.75,
                "mission_group_id": mission_group_id,
                "time_range": {
                    "start": start_time.isoformat(),
                    "end": now_utc().isoformat()
                }
            }
        
        try:
            # Initialize table service client
            table_service = TableServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
            table_client = table_service.get_table_client(table_name=STORAGE_TABLE_NAME)
            
            # Query for messages in the time range and group
            end_time = now_utc()
            start_timestamp = start_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            end_timestamp = end_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            
            # Build query filter for the time range only (don't filter by group)
            # The simulator sends messages to multiple groups, so we need all messages in the time window
            query_filter = f"PartitionKey eq 'messages' and Timestamp ge datetime'{start_timestamp}' and Timestamp le datetime'{end_timestamp}'"
            
            logger.info(f"Querying Azure Table Storage with filter: {query_filter}")
            
            # Execute query
            entities = list(table_client.query_entities(query_filter=query_filter))
            logger.info(f"Found {len(entities)} entities in table storage")
            
            # Process results into responder summary
            responders = {}
            total_messages = 0
            
            for entity in entities:
                # Use the actual field names from the table
                sender_name = entity.get('name', 'Unknown')
                message_text = entity.get('text', '')
                message_type = entity.get('arrival_status', 'unknown')
                
                if sender_name not in responders:
                    responders[sender_name] = {
                        "name": sender_name,
                        "messages": 0,
                        "message_texts": [],
                        "message_types": [],
                        "status": "responded"
                    }
                
                responders[sender_name]["messages"] += 1
                responders[sender_name]["message_texts"].append(message_text)
                responders[sender_name]["message_types"].append(message_type)
                total_messages += 1
                
                # Determine status based on message content
                if any(word in message_text.lower() for word in ['cancel', 'backing out', 'can\'t make', 'unable']):
                    responders[sender_name]["status"] = "cancelled"
            
            # Calculate response rate
            response_rate = len([r for r in responders.values() if r["status"] == "responded"]) / max(len(responders), 1)
            
            result = {
                "responders": list(responders.values()),
                "total_messages": total_messages,
                "response_rate": response_rate,
                "mission_group_id": mission_group_id,
                "time_range": {
                    "start": start_time.isoformat(),
                    "end": end_time.isoformat()
                },
                "query_info": {
                    "table_name": STORAGE_TABLE_NAME,
                    "entities_found": len(entities)
                }
            }
            
            logger.info(f"Processed {len(responders)} responders with {total_messages} total messages")
            return result
            
        except Exception as e:
            logger.error(f"Error fetching responder results from Azure Storage: {e}")
            logger.error(f"Exception type: {type(e).__name__}")
            # Fall back to mock data on error
            return self._fetch_responder_results_from_storage(mission_group_id, start_time)  # Use dry run mock

    def _fetch_responder_results(self, mission_group_id: str, start_time: datetime) -> Optional[Dict[str, Any]]:
        """
        Fetch responder results for post-mission analysis.
        Uses Azure Table Storage directly instead of API calls.
        """
        return self._fetch_responder_results_from_storage(mission_group_id, start_time)

    def _perform_post_mission_analysis(self, mission_data: Dict[str, Any], start_time: datetime) -> None:
        """
        Perform post-mission analysis by calling the LLM to grade message parsing and interpretation.
        """
        logger.info("Starting post-mission analysis...")
        
        # Fetch responder results from the API
        responder_results = self._fetch_responder_results(mission_data["mission_group_id"], start_time)
        if not responder_results:
            logger.warning("Could not fetch responder results, skipping post-mission analysis")
            return
        
        # Perform LLM analysis
        analysis = self.planner.analyze_mission_performance(mission_data, responder_results)
        if not analysis:
            logger.warning("LLM analysis failed, skipping post-mission analysis")
            return
        
        # Save analysis results
        ensure_dir("missions")
        analysis_path = os.path.join("missions", f"{start_time.strftime('%Y%m%dT%H%M%SZ')}-analysis.json")
        try:
            with open(analysis_path, "w", encoding="utf-8") as f:
                json.dump(analysis, f, indent=2)
            logger.info(f"Mission analysis written to {analysis_path}")
        except Exception as e:
            logger.debug(f"Failed to write mission analysis: {e}")
        
        # Display analysis summary
        self._display_analysis_summary(analysis)

    def _display_analysis_summary(self, analysis: Dict[str, Any]) -> None:
        """
        Display a formatted summary of the mission analysis.
        """
        logger.info("=" * 60)
        logger.info("MISSION PERFORMANCE ANALYSIS")
        logger.info("=" * 60)
        
        # Overall scores
        overall_score = analysis.get("overall_score", "N/A")
        parsing_accuracy = analysis.get("parsing_accuracy", "N/A")
        interpretation_quality = analysis.get("interpretation_quality", "N/A")
        
        logger.info(f"Overall Score: {overall_score}")
        logger.info(f"Parsing Accuracy: {parsing_accuracy}")
        logger.info(f"Interpretation Quality: {interpretation_quality}")
        logger.info("")
        
        # Message grades table
        message_grades = analysis.get("message_grades", [])
        if message_grades:
            logger.info("MESSAGE GRADING TABLE:")
            logger.info("-" * 60)
            logger.info(f"{'#':<3} {'Sender':<15} {'Grade':<5} {'Message':<35}")
            logger.info("-" * 60)
            
            for i, msg in enumerate(message_grades):
                sender = msg.get("sender", "Unknown")[:14]
                grade = msg.get("grade", "N/A")
                message_text = msg.get("message_text", "")[:34]
                logger.info(f"{i+1:<3} {sender:<15} {grade:<5} {message_text:<35}")
            
            logger.info("-" * 60)
        
        # Summary
        summary = analysis.get("summary", {})
        strengths = summary.get("strengths", [])
        weaknesses = summary.get("weaknesses", [])
        recommendations = summary.get("recommendations", [])
        
        if strengths:
            logger.info("STRENGTHS:")
            for strength in strengths:
                logger.info(f"  + {strength}")
            logger.info("")
        
        if weaknesses:
            logger.info("WEAKNESSES:")
            for weakness in weaknesses:
                logger.info(f"  - {weakness}")
            logger.info("")
        
        if recommendations:
            logger.info("RECOMMENDATIONS:")
            for rec in recommendations:
                logger.info(f"  → {rec}")
            logger.info("")
        
        logger.info("=" * 60)

    # ---------------- Mission engine ----------------
    def simulate_one_mission(self) -> None:
        logger.info("Starting mission simulation...")
        mission_group_id = self._select_mission_group()

        # Optionally authenticate for keepalive (not required)
        self._authenticate()

        # Select location
        location = random.choice(self.snohomish_locations)

        # Build alert from template (keeps your current style)
        alert_text = self.generate_mission_alert(location)
        logger.info(f"Mission: {location.name}")
        logger.info(f"Alert: {alert_text}")

        # Mission start time (UTC)
        start_time = now_utc()

        # LLM planning step (cast + timeline)
        plan_raw: Optional[Dict[str, Any]] = None
        if self.planner.available():
            plan_raw = self.planner.plan_mission(
                mission_group_id=mission_group_id,
                location=location,
                start_time_utc=start_time,
                min_team=self.min_team,
                max_team=self.max_team,
                min_window_min=self.min_window_min,
                max_window_min=self.max_window_min,
            )

        plan_source = "llm" if plan_raw else "fallback"

        # Fallback simple plan if LLM unavailable/failed
        if not plan_raw:
            logger.warning("LLM planning unavailable; falling back to template-based plan.")
            plan_raw = self._fallback_plan(location, start_time, mission_group_id)

        # Validate / materialize
        team, messages, window_minutes = self._validate_and_materialize_plan(
            plan_raw, mission_group_id, (self.min_window_min, self.max_window_min)
        )

        if plan_source == "llm" and (not team or not messages):
            logger.warning("LLM plan missing required sections; regenerating via template fallback.")
            plan_raw = self._fallback_plan(location, start_time, mission_group_id)
            plan_source = "fallback"
            team, messages, window_minutes = self._validate_and_materialize_plan(
                plan_raw, mission_group_id, (self.min_window_min, self.max_window_min)
            )

        if not team:
            logger.error("No team in plan after fallback; aborting mission.")
            return
        if not messages:
            logger.error("No messages in plan after fallback; aborting mission.")
            return

        # Log unique home groups after team materialization
        unique_home_groups = sorted({r.home_group_id for r in team if r.home_group_id})
        logger.info(f"Team materialized with {len(unique_home_groups)} unique home groups: {[REAL_GROUP_IDS.get(gid, gid) for gid in unique_home_groups]}")

        # Persist mission plan for audit/replay
        ensure_dir("missions")
        plan_path = os.path.join("missions", f"{start_time.strftime('%Y%m%dT%H%M%SZ')}-mission.json")
        try:
            with open(plan_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "started_utc": start_time.isoformat(),
                        "mission_group_id": mission_group_id,
                        "location": {
                            "name": location.name,
                            "coordinates": location.coordinates,
                            "trail_description": location.trail_description,
                        },
                        "plan_raw": plan_raw,
                        "window_minutes": window_minutes,
                        "team": [t.__dict__ for t in team],
                        "messages": [m.__dict__ for m in messages],
                        "routing": {
                            "mode": self.group_mode,
                            "unique_home_groups": unique_home_groups,
                            "home_group_names": [REAL_GROUP_IDS.get(gid, gid) for gid in unique_home_groups]
                        },
                    },
                    f,
                    indent=2,
                )
            logger.info(f"Mission plan written to {plan_path}")
        except Exception as e:
            logger.debug(f"Failed to write mission plan: {e}")

        # Start keepalive for the window
        keepalive_thread = self.start_website_keepalive(expected_minutes=window_minutes)

        try:
            # Send initial alert from IC
            ic = Responder(
                name="SAR Command",
                user_id="999999999",
                sender_id="999999999",
                experience_level="veteran",
                response_probability=1.0,
                vehicle_preference="Command",
                personality="precise",
                mission_group_id=mission_group_id,
                home_group_id="96018206",  # IMT group ID
            )
            
            # Use routing-aware alert sending
            logger.info(f"Routing mode: {self.group_mode}")
            self._send_initial_alerts(ic, alert_text, team, mission_group_id)

            # Feed messages over time based on offsets (scaled by --speed)
            start_monotonic = time.monotonic()
            for msg in messages:
                due = msg.offset_sec / self.speed
                now = time.monotonic()
                if due > now - start_monotonic:
                    time.sleep(due - (now - start_monotonic))

                sender = team[msg.sender_index]
                # Route message based on group mode and message type
                target_group_id = self._route_group_id(sender, msg.type, mission_group_id)
                self.send_message(
                    group_id=target_group_id,
                    name=sender.name,
                    sender_id=sender.sender_id,
                    user_id=sender.user_id,
                    text=msg.text,
                )

            logger.info("Mission simulation completed.")
            self._update_last_mission_time()
            
            # Perform post-mission analysis
            mission_data = {
                "started_utc": start_time.isoformat(),
                "mission_group_id": mission_group_id,
                "location": {
                    "name": location.name,
                    "coordinates": location.coordinates,
                    "trail_description": location.trail_description,
                },
                "plan_raw": plan_raw,
                "window_minutes": window_minutes,
                "team": [t.__dict__ for t in team],
                "messages": [m.__dict__ for m in messages],
                "routing": {
                    "mode": self.group_mode,
                    "unique_home_groups": unique_home_groups,
                    "home_group_names": [REAL_GROUP_IDS.get(gid, gid) for gid in unique_home_groups]
                },
            }
            self._perform_post_mission_analysis(mission_data, start_time)
            
        finally:
            # Stop keepalive gracefully
            self.stop_website_keepalive()
            keepalive_thread.join(timeout=5)

    def _fallback_plan(self, location: MissionLocation, start: datetime, mission_group_id: str) -> Dict[str, Any]:
        """
        Deterministic template-based fallback: build cast + timeline locally.
        """
        team_size = random.randint(self.min_team, self.max_team)
        # Generate a name pool
        first_names = [
            "Mike", "Sarah", "David", "Jessica", "Chris", "Amanda", "Ryan", "Lisa",
            "Kevin", "Jennifer", "Mark", "Emily", "Jason", "Ashley", "Brian", "Michelle",
            "Steve", "Nicole", "Matt", "Stephanie", "Dan", "Rachel", "Tom", "Melissa",
            "John", "Amy", "Rob", "Heather", "Scott", "Katie", "Jim", "Lindsey",
            "Paul", "Kristen", "Ben", "Angela", "Adam", "Samantha", "Jake", "Brittany",
        ]
        last_names = [
            "Anderson", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
            "Wilson", "Martinez", "Taylor", "Thomas", "Jackson", "White", "Harris", "Martin",
            "Thompson", "Moore", "Young", "Allen", "King", "Wright", "Lopez", "Hill",
            "Green", "Adams", "Baker", "Nelson", "Carter", "Mitchell", "Perez", "Roberts",
            "Turner", "Phillips", "Campbell", "Parker", "Evans", "Edwards", "Collins", "Stewart",
        ]
        def mkname(): return f"{random.choice(first_names)} {random.choice(last_names)}"

        team = []
        for _ in range(team_size):
            team.append({
                "name": mkname(),
                "experience_level": random.choices(["rookie", "experienced", "veteran"], weights=[0.3, 0.5, 0.2])[0],
                "personality": random.choice(["precise", "casual", "talkative", "quiet"]),
                "vehicle_preference": random.choice(["POV", f"SAR-{random.randint(1,99)}", "SAR Rig"]),
                "home_group_id": rand_group_id(),
            })

        window_minutes = random.randint(self.min_window_min, self.max_window_min)
        total = window_minutes * 60

        # Build a front-loaded timeline
        msgs = []
        # initial responses: about team_size people, but not everyone
        initial_count = int(team_size * random.uniform(0.6, 0.85))
        for i in range(initial_count):
            sender_idx = i if i < team_size else random.randrange(team_size)
            offset = clamp(random.expovariate(1/300.0), 0, total)  # many in first ~5 min
            text = random.choice([
                "Responding POV ETA 20 min",
                "En route SAR-{}".format(random.randint(1, 99)),
                "At TH in 30",
                "Rolling, ETA {}".format(random.choice(["1745", "18:05", "25 min"])),
                "Leaving now, bringing med kit",
            ])
            msgs.append({"sender_index": sender_idx, "type": "initial_response", "text": text, "offset_sec": offset})

        # follow-ups/status
        follow_count = int(team_size * random.uniform(0.2, 0.35))
        for _ in range(follow_count):
            sender_idx = random.randrange(team_size)
            offset = clamp(random.uniform(total * 0.25, total), 0, total)
            text = random.choice([
                "Park at TH or overflow?",
                "Traffic heavy, 10 late",
                "At TH, heading up",
                "Need extra water?",
                "Radio check from TH",
            ])
            msgs.append({"sender_index": sender_idx, "type": random.choice(["followup", "status"]), "text": text, "offset_sec": offset})

        # cancellations
        cancel_count = max(1, int(initial_count * random.uniform(0.05, 0.12)))
        for _ in range(cancel_count):
            sender_idx = random.randrange(team_size)
            offset = clamp(random.uniform(total * 0.2, total * 0.8), 0, total)
            text = random.choice([
                "Backing out, work call",
                "Vehicle issue, canceling",
                "Family conflict, can't make it",
                "Sick, standing down",
            ])
            msgs.append({"sender_index": sender_idx, "type": "cancellation", "text": text, "offset_sec": offset})

        msgs.sort(key=lambda m: m["offset_sec"])
        return {"team": team, "messages": msgs, "window_minutes": window_minutes}

    # ---------------- Cadence control ----------------
    def should_start_mission(self) -> bool:
        last_mission_file = "last_mission.txt"
        try:
            if os.path.exists(last_mission_file):
                with open(last_mission_file, "r") as f:
                    last_time = float(f.read().strip())
                    hours_since = (time.time() - last_time) / 3600
                    return hours_since >= 48
            else:
                return True
        except Exception:
            return True

    def _update_last_mission_time(self):
        with open("last_mission.txt", "w") as f:
            f.write(str(time.time()))

    def run_forever(self, force_once: bool = False):
        """
        Continuous runner: respects 48h cadence; --force-mission runs one immediately this process.
        """
        did_force = False
        try:
            while True:
                if force_once and not did_force:
                    logger.info("Force mode: running mission now.")
                    self.simulate_one_mission()
                    did_force = True
                elif self.should_start_mission():
                    self.simulate_one_mission()
                else:
                    # Sleep in short chunks to remain responsive to Ctrl-C
                    try:
                        with open("last_mission.txt", "r") as f:
                            last = float(f.read().strip())
                    except Exception:
                        last = time.time()
                    elapsed = time.time() - last
                    remain = max(0, 48 * 3600 - elapsed)
                    human = str(timedelta(seconds=int(remain)))
                    logger.info(f"No mission needed yet. Next in ~{human}. Sleeping 10 minutes.")
                    for _ in range(60):  # 60 * 10s = 10 minutes
                        time.sleep(10)
                # Loop back to check again
        except KeyboardInterrupt:
            logger.info("Shutting down (Ctrl-C). Bye.")

# -----------------------------------------------------------
# CLI
# -----------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(description="Mission Simulator for Respondr Lite (Supercharged)")
    p.add_argument("--dry-run", action="store_true", help="Simulate without sending actual messages")
    p.add_argument("--force-mission", action="store_true", help="Run a mission now (ignores 48h this run)")
    p.add_argument("--speed", type=float, default=float(os.getenv("SIM_SPEED", "1.0")),
                   help="Time acceleration factor for in-mission timing (e.g., 2.0 = twice as fast)")
    p.add_argument("--min-team", type=int, default=int(os.getenv("SIM_MIN_TEAM", "10")),
                   help="Minimum team size")
    p.add_argument("--max-team", type=int, default=int(os.getenv("SIM_MAX_TEAM", "40")),
                   help="Maximum team size")
    p.add_argument("--min-window", type=int, default=int(os.getenv("SIM_MIN_WINDOW_MIN", "30")),
                   help="Minimum message window minutes")
    p.add_argument("--max-window", type=int, default=int(os.getenv("SIM_MAX_WINDOW_MIN", "60")),
                   help="Maximum message window minutes")
    p.add_argument("--group-mode",
                   choices=["single", "multi", "split"],
                   default=os.getenv("SIM_GROUP_MODE", "single"),
                   help=("Routing strategy: "
                         "'single' = all messages to one mission thread; "
                         "'multi' = each responder posts to their home_group_id; "
                         "'split' = initial responses to home_group_id, follow-ups/status to mission thread"))
    return p.parse_args()

def main():
    args = parse_args()
    sim = MissionSimulator(
        dry_run=args.dry_run,
        speed=args.speed,
        min_team=args.min_team,
        max_team=args.max_team,
        min_window_min=args.min_window,
        max_window_min=args.max_window,
        group_mode=args.group_mode,
    )
    sim.run_forever(force_once=args.force_mission)

if __name__ == "__main__":
    main()
