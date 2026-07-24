"""Privacy-safe, team-aware synthetic SAR message generation."""

from __future__ import annotations

import json
import random
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol


TEAM_GROUP_IDS: dict[str, str] = {
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

VALID_STATUSES = {
    "Responding",
    "Available",
    "Informational",
    "Cancelled",
    "Not Responding",
    "Unknown",
}
VALID_ETA_MODES = {"none", "relative", "clock", "military"}
PII_PATTERNS = (
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"https?://\S+", re.IGNORECASE),
    re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b"),
    re.compile(r"\b-?\d{2,3}\.\d{3,}\s*,\s*-?\d{2,3}\.\d{3,}\b"),
)


def load_team_profiles(path: str | Path | None = None) -> dict[str, Any]:
    profile_path = (
        Path(path)
        if path
        else Path(__file__).with_name("team_message_profiles.json")
    )
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0":
        raise ValueError("Unsupported team profile schema")
    teams = payload.get("teams")
    if not isinstance(teams, dict) or not teams:
        raise ValueError("Team profiles are missing")
    return payload


@dataclass(frozen=True)
class MessageRequest:
    request_id: str
    team: str
    status: str
    vehicle: str = "Unknown"
    eta_mode: str = "none"
    eta_minutes: int = 20
    message_type: str = "initial_response"

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Unsupported status: {self.status}")
        if self.eta_mode not in VALID_ETA_MODES:
            raise ValueError(f"Unsupported ETA mode: {self.eta_mode}")
        if not self.request_id:
            raise ValueError("request_id is required")


@dataclass
class GeneratedMessage:
    request_id: str
    team: str
    status: str
    text: str
    strategy: str
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CorpusMessage:
    team: str
    status: str
    vehicle: str
    text: str
    mission_hash: str
    eta_iso: str = "Unknown"


class MessageGenerator(Protocol):
    name: str

    def generate_batch(
        self, requests: list[MessageRequest]
    ) -> list[GeneratedMessage]:
        ...


RESPONDING_TEMPLATES: dict[str, tuple[str, ...]] = {
    "4X4": (
        "4X4 driver responding {vehicle}, ETA {eta}",
        "Responding with {vehicle} for access support, ETA {eta}",
    ),
    "ASAR": (
        "ASAR responding {vehicle}, ETA {eta}",
        "Ground responder en route {vehicle}, ETA {eta}",
    ),
    "ESAR": (
        "ESAR responding {vehicle}, ETA {eta}",
        "En route to staging {vehicle}, ETA {eta}",
    ),
    "IMT": (
        "IMT responding to ICP {vehicle}, ETA {eta}",
        "Operations support en route, ETA {eta}",
    ),
    "K9": (
        "K9 handler responding {vehicle}, ETA {eta}",
        "Handler and K9 en route, ETA {eta}",
    ),
    "MSAR": (
        "MSAR responding {vehicle}, ETA {eta}",
        "{vehicle} en route to staging, ETA {eta}",
    ),
    "OSU": (
        "OSU support responding {vehicle}, ETA {eta}",
        "Operations support en route, ETA {eta}",
    ),
    "SSAR": (
        "SSAR responding {vehicle}, ETA {eta}",
        "{vehicle} en route to the trailhead, ETA {eta}",
    ),
    "Tracker": (
        "Tracker responding {vehicle}, ETA {eta}",
        "Tracking support en route, ETA {eta}",
    ),
}

INFORMATIONAL_TEMPLATES: dict[str, tuple[str, ...]] = {
    "4X4": (
        "The SAR Rig is ready at staging",
        "Confirm the driver assignment for access support",
        "Do we need another four-wheel-drive vehicle",
    ),
    "ASAR": (
        "Confirm the ASAR hasty assignment",
        "Ground team is checking in at staging",
        "Which trailhead should ASAR use",
    ),
    "ESAR": (
        "ESAR received the team assignment",
        "Confirm the ESAR staging location",
        "Ground team status is current",
    ),
    "IMT": (
        "Operations is setting assignments at ICP",
        "Planning has the current team list",
        "Confirm the staging location with logistics",
    ),
    "K9": (
        "K9 needs a clean scent article",
        "Handler is coordinating field support",
        "Confirm K9 staging",
    ),
    "MSAR": (
        "Confirm the MSAR vehicle assignment",
        "MSAR is checking vehicle status at the station",
        "Which staging area should MSAR use",
    ),
    "OSU": (
        "OSU is available for logistics support",
        "Radio support is ready at staging",
        "Confirm the OSU assignment",
    ),
    "SSAR": (
        "Confirm the SSAR hasty assignment",
        "SSAR is checking vehicle status at the station",
        "Which trailhead should SSAR use",
    ),
    "Tracker": (
        "Tracker team is checking the last known point",
        "Confirm the tracker assignment",
        "Tracking support is ready at staging",
    ),
}

STATUS_TEMPLATES: dict[str, tuple[str, ...]] = {
    "Available": (
        "Available if another team is needed",
        "Standing by and available",
        "Available for field support",
    ),
    "Not Responding": (
        "I cannot respond tonight",
        "Unavailable for this mission",
        "I cannot make this call",
    ),
    "Cancelled": (
        "Cancel my response due to a vehicle issue",
        "Standing down from my response",
        "I have to cancel my response",
    ),
    "Unknown": (
        "Copy",
        "Received",
        "Thanks for the update",
    ),
}

FOLLOWUP_TEMPLATES: dict[str, tuple[str, ...]] = {
    "4X4": (
        "At staging with the vehicle",
        "Access route is clear",
    ),
    "ASAR": (
        "At the trailhead and starting the assignment",
        "Ground team is at staging",
    ),
    "ESAR": (
        "At staging and ready for assignment",
        "Team is checking in with operations",
    ),
    "IMT": (
        "At ICP and checking in with operations",
        "Planning assignment received",
    ),
    "K9": (
        "K9 is at staging",
        "Scent article received",
    ),
    "MSAR": (
        "At the station with the assigned vehicle",
        "MSAR is at staging",
    ),
    "OSU": (
        "At staging with radio support",
        "OSU assignment received",
    ),
    "SSAR": (
        "At the trailhead with the assigned vehicle",
        "SSAR is at staging",
    ),
    "Tracker": (
        "At the last known point",
        "Tracker assignment received",
    ),
}

TEAM_ETA_MODES: dict[str, tuple[str, ...]] = {
    "ASAR": ("military", "clock", "relative"),
    "IMT": ("military", "relative", "clock"),
    "K9": ("clock", "military", "relative"),
    "MSAR": ("military", "clock"),
    "SSAR": ("clock", "military"),
    "Tracker": ("military", "clock", "relative"),
}


def _weighted_choice(rng: random.Random, counts: Mapping[str, int]) -> str:
    values = [(key, int(value)) for key, value in counts.items() if int(value) > 0]
    if not values:
        return "Unknown"
    return rng.choices(
        [item[0] for item in values],
        weights=[item[1] for item in values],
        k=1,
    )[0]


def contains_pii(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in PII_PATTERNS)


def sanitize_generated_text(text: str, max_words: int = 40) -> str:
    value = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
    for pattern in PII_PATTERNS:
        value = pattern.sub("[redacted]", value)
    words = value.split()
    if len(words) > max_words:
        value = " ".join(words[:max_words])
    return value.strip(" \t\r\n\"'")


def _format_eta(request: MessageRequest, rng: random.Random) -> str:
    mode = request.eta_mode
    if mode == "none":
        return ""
    if mode == "relative":
        minutes = max(5, min(120, int(request.eta_minutes)))
        return f"{minutes} min"
    hour = rng.randint(17, 22)
    minute = rng.choice((0, 5, 10, 15, 20, 30, 40, 45, 50, 55))
    if mode == "clock":
        return f"{hour}:{minute:02d}"
    return f"{hour:02d}{minute:02d}"


def has_eta_mode(text: str, request: MessageRequest) -> bool:
    if request.eta_mode == "relative":
        return bool(
            re.search(
                rf"\b{max(5, min(120, int(request.eta_minutes)))}\s*"
                r"(?:min|minutes)\b",
                text,
                re.IGNORECASE,
            )
        )
    if request.eta_mode == "clock":
        return bool(
            re.search(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", text)
        )
    if request.eta_mode == "military":
        return bool(re.search(r"(?<![-\d])(?:[01]\d|2[0-3])[0-5]\d(?!\d)", text))
    return not re.search(
        r"\beta\b|\b\d{1,3}\s*(?:min|minutes)\b|"
        r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b|"
        r"(?<![-\d])(?:[01]\d|2[0-3])[0-5]\d(?!\d)",
        text,
        re.IGNORECASE,
    )


def _has_status_cue(text: str, status: str) -> bool:
    patterns = {
        "Responding": r"\b(responding|en route|heading|leaving|on my way)\b",
        "Available": r"\b(available|standing by)\b",
        "Not Responding": r"\b(cannot|can't|unable|unavailable|not responding)\b",
        "Cancelled": r"\b(cancel(?:led|ing)?|standing down|10-22)\b",
    }
    matches = {
        name
        for name, pattern in patterns.items()
        if re.search(pattern, text, re.IGNORECASE)
    }
    if status in patterns:
        return status in matches
    return not matches


def _has_vehicle(text: str, vehicle: str) -> bool:
    any_vehicle = re.search(
        r"\bpov\b|\bsar(?:\s+rig|[- ]?\d{1,3})\b|"
        r"\b(?:car|vehicle|rig)\b",
        text,
        re.IGNORECASE,
    )
    if vehicle == "Unknown":
        return not any_vehicle
    if vehicle == "POV":
        return bool(re.search(r"\bpov\b|\b(?:car|personal vehicle)\b", text, re.IGNORECASE))
    if vehicle == "SAR Rig":
        return bool(re.search(r"\bsar\s+rig\b", text, re.IGNORECASE))
    number = re.search(r"\d{1,3}", vehicle)
    if number:
        return bool(
            re.search(
                rf"\bsar[- ]?0*{re.escape(number.group(0))}\b",
                text,
                re.IGNORECASE,
            )
        )
    return vehicle.lower() in text.lower()


def _strip_absence_markers(text: str) -> str:
    value = re.sub(
        r"(?:unknown vehicle|vehicle unknown|no vehicle)(?:[.,;:]|\b)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"(?:no eta|eta unknown|without an eta)(?:[.,;:]|\b)",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return sanitize_generated_text(value)


class HeuristicMessageGenerator:
    """Generate controlled messages from privacy-safe team templates."""

    name = "heuristic-templates-v2"

    def __init__(
        self,
        seed: int = 20260724,
        profiles: dict[str, Any] | None = None,
    ):
        self.rng = random.Random(seed)
        self.profile_payload = profiles or load_team_profiles()
        self.profiles = self.profile_payload["teams"]

    def sample_vehicle(self, team: str, allow_unknown: bool = False) -> str:
        profile = self.profiles.get(team) or {}
        counts = dict(profile.get("vehicle_counts") or {"POV": 1})
        if not allow_unknown:
            counts.pop("Unknown", None)
        vehicle = _weighted_choice(self.rng, counts)
        return "POV" if vehicle == "Unknown" else vehicle

    def sample_response_status(self, team: str) -> str:
        profile = self.profiles.get(team) or {}
        counts = dict(profile.get("status_counts") or {"Responding": 1})
        allowed = {
            key: value
            for key, value in counts.items()
            if key in {"Responding", "Available", "Not Responding"}
        }
        return _weighted_choice(self.rng, allowed)

    def sample_eta_mode(self, team: str) -> str:
        return self.rng.choice(TEAM_ETA_MODES.get(team, ("relative", "military")))

    def generate(self, request: MessageRequest) -> GeneratedMessage:
        started = time.perf_counter()
        team = request.team if request.team in self.profiles else "ASAR"
        if request.message_type in {"followup", "status"}:
            templates = FOLLOWUP_TEMPLATES.get(team, FOLLOWUP_TEMPLATES["ASAR"])
            text = self.rng.choice(templates)
        elif request.status == "Responding":
            templates = RESPONDING_TEMPLATES.get(team, RESPONDING_TEMPLATES["ASAR"])
            vehicle = request.vehicle
            eta = _format_eta(request, self.rng)
            if vehicle == "Unknown" and not eta:
                text = "Responding"
            elif vehicle == "Unknown":
                text = f"Responding, ETA {eta}"
            elif not eta:
                text = f"Responding {vehicle}"
            else:
                text = self.rng.choice(templates).format(
                    vehicle=vehicle,
                    eta=eta,
                )
                if vehicle.lower() not in text.lower():
                    text = f"{text} {vehicle}"
        elif request.status == "Informational":
            templates = INFORMATIONAL_TEMPLATES.get(
                team, INFORMATIONAL_TEMPLATES["ASAR"]
            )
            text = self.rng.choice(templates)
        else:
            text = self.rng.choice(STATUS_TEMPLATES[request.status])
        text = sanitize_generated_text(text)
        return GeneratedMessage(
            request_id=request.request_id,
            team=request.team,
            status=request.status,
            text=text,
            strategy=self.name,
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    def generate_batch(
        self, requests: list[MessageRequest]
    ) -> list[GeneratedMessage]:
        return [self.generate(request) for request in requests]


SAFE_WORDS = {
    "a",
    "about",
    "access",
    "all",
    "and",
    "another",
    "are",
    "assignment",
    "at",
    "available",
    "back",
    "be",
    "bringing",
    "call",
    "cancel",
    "cancelled",
    "cannot",
    "car",
    "checking",
    "clear",
    "confirm",
    "copy",
    "delayed",
    "driver",
    "en",
    "eta",
    "field",
    "for",
    "from",
    "ground",
    "handler",
    "hasty",
    "have",
    "heading",
    "ic",
    "icp",
    "if",
    "in",
    "is",
    "k9",
    "last",
    "late",
    "leaving",
    "location",
    "logistics",
    "make",
    "min",
    "minutes",
    "mission",
    "my",
    "need",
    "needed",
    "not",
    "now",
    "of",
    "on",
    "operations",
    "ops",
    "out",
    "planning",
    "point",
    "pov",
    "radio",
    "received",
    "respond",
    "responding",
    "response",
    "rig",
    "route",
    "sar",
    "scent",
    "search",
    "station",
    "staging",
    "stand",
    "standing",
    "starting",
    "support",
    "team",
    "the",
    "this",
    "to",
    "tonight",
    "tracker",
    "tracking",
    "trailhead",
    "unable",
    "unavailable",
    "vehicle",
    "with",
}
TOKEN_PATTERN = re.compile(
    r"SAR[- ]?\d{1,3}|10[- ]?22|K9|"
    r"(?:[01]?\d|2[0-3]):[0-5]\d|"
    r"(?:[01]\d|2[0-3])[0-5]\d|"
    r"[A-Za-z]+(?:'[A-Za-z]+)?",
    re.IGNORECASE,
)


def _safe_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for match in TOKEN_PATTERN.finditer(text or ""):
        token = match.group(0)
        lowered = token.lower()
        sar = re.fullmatch(r"sar[- ]?0*(\d{1,3})", lowered)
        if sar:
            unit = int(sar.group(1))
            if 1 <= unit <= 199:
                tokens.append(f"SAR-{unit}")
            continue
        if re.fullmatch(r"10[- ]?22", lowered):
            tokens.append("10-22")
            continue
        if re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d", lowered):
            tokens.append(lowered)
            continue
        if re.fullmatch(r"(?:[01]\d|2[0-3])[0-5]\d", lowered):
            tokens.append(lowered)
            continue
        if lowered in SAFE_WORDS:
            tokens.append(lowered)
    return tokens


class NgramMessageGenerator:
    """Generate messages with a conditional word-bigram model."""

    name = "conditional-bigram-v1"

    def __init__(
        self,
        seed: int = 20260724,
        profiles: dict[str, Any] | None = None,
    ):
        self.rng = random.Random(seed)
        self.profiles = (profiles or load_team_profiles())["teams"]
        self.transitions: dict[
            tuple[str, str], dict[str, Counter[str]]
        ] = defaultdict(lambda: defaultdict(Counter))
        self.starts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
        self.fallback = HeuristicMessageGenerator(seed=seed + 1, profiles=profiles)
        self.training_count = 0

    def fit(self, messages: Iterable[CorpusMessage]) -> None:
        for message in messages:
            tokens = _safe_tokens(message.text)
            if len(tokens) < 2:
                continue
            keys = ((message.team, message.status), (message.team, "*"))
            for key in keys:
                self.starts[key][tokens[0]] += 1
                previous = "<start>"
                for token in tokens:
                    self.transitions[key][previous][token] += 1
                    previous = token
                self.transitions[key][previous]["<end>"] += 1
            self.training_count += 1

    def _draw(self, values: Counter[str]) -> str | None:
        if not values:
            return None
        return self.rng.choices(
            list(values),
            weights=list(values.values()),
            k=1,
        )[0]

    def _generate_tokens(self, request: MessageRequest) -> list[str]:
        key = (
            (request.team, request.status)
            if self.starts.get((request.team, request.status))
            else (request.team, "*")
        )
        start = self._draw(self.starts.get(key, Counter()))
        if not start:
            return []
        profile = self.profiles.get(request.team) or {}
        max_words = max(5, min(30, int(profile.get("p90_words") or 18)))
        result = [start]
        previous = start
        while len(result) < max_words:
            token = self._draw(self.transitions.get(key, {}).get(previous, Counter()))
            if not token or token == "<end>":
                break
            result.append(token)
            previous = token
        return result

    def _ensure_controls(self, text: str, request: MessageRequest) -> str:
        lowered = text.lower()
        if request.status == "Responding" and not re.search(
            r"\b(responding|en route|heading|leaving)\b", lowered
        ):
            text = f"Responding {text}"
        elif request.status == "Available" and "available" not in lowered:
            text = f"Available for support. {text}"
        elif request.status == "Not Responding" and not re.search(
            r"\b(cannot|unavailable|not responding)\b", lowered
        ):
            text = f"Cannot respond. {text}"
        elif request.status == "Cancelled" and not re.search(
            r"\b(cancel|standing down|10-22)\b", lowered
        ):
            text = f"Cancel my response. {text}"
        if (
            request.status == "Responding"
            and request.vehicle != "Unknown"
            and request.vehicle.lower() not in text.lower()
        ):
            text = f"{text} {request.vehicle}"
        if (
            request.status == "Responding"
            and request.eta_mode != "none"
            and not has_eta_mode(text, request)
        ):
            text = f"{text} ETA {_format_eta(request, self.rng)}"
        return sanitize_generated_text(text)

    def generate(self, request: MessageRequest) -> GeneratedMessage:
        started = time.perf_counter()
        tokens = self._generate_tokens(request)
        if len(tokens) < 2:
            fallback = self.fallback.generate(request)
            fallback.strategy = self.name
            fallback.metadata["fallback"] = "heuristic"
            return fallback
        text = " ".join(tokens)
        text = self._ensure_controls(text, request)
        return GeneratedMessage(
            request_id=request.request_id,
            team=request.team,
            status=request.status,
            text=text,
            strategy=self.name,
            latency_ms=(time.perf_counter() - started) * 1000,
            metadata={"fallback": None},
        )

    def generate_batch(
        self, requests: list[MessageRequest]
    ) -> list[GeneratedMessage]:
        return [self.generate(request) for request in requests]


class AIMessageGenerator:
    """Generate synthetic messages from aggregate team profiles."""

    name = "ai-profile-v1"

    def __init__(
        self,
        client: Any,
        deployment: str,
        model_id: str,
        profiles: dict[str, Any] | None = None,
        reasoning_effort: str = "minimal",
        verbosity: str = "low",
        max_tokens: int = 4096,
    ):
        if client is None:
            raise ValueError("client is required")
        if not deployment:
            raise ValueError("deployment is required")
        self.client = client
        self.deployment = deployment
        self.model_id = model_id
        self.profiles = (profiles or load_team_profiles())["teams"]
        self.reasoning_effort = reasoning_effort
        self.verbosity = verbosity
        self.max_tokens = max_tokens
        self.fallback = HeuristicMessageGenerator(seed=20260724, profiles=profiles)

    def _profile_summary(self, teams: set[str]) -> dict[str, Any]:
        return {
            team: {
                "median_words": self.profiles[team]["median_words"],
                "p90_words": self.profiles[team]["p90_words"],
                "semantic_focus": self.profiles[team]["semantic_focus"],
                "preferred_vehicles": [
                    vehicle
                    for vehicle, _ in sorted(
                        self.profiles[team]["vehicle_counts"].items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                    if vehicle != "Unknown"
                ][:4],
            }
            for team in sorted(teams)
            if team in self.profiles
        }

    def generate_batch(
        self, requests: list[MessageRequest]
    ) -> list[GeneratedMessage]:
        if not requests:
            return []
        started = time.perf_counter()
        system = (
            "Generate synthetic Search and Rescue chat messages. "
            "Use short, informal, operational text. "
            "Follow each requested team, status, vehicle, ETA mode, and message type. "
            "Use American English and ASCII punctuation only. "
            "Use no more than 20 words in each message. "
            "Unknown vehicle means that you must not mention a vehicle. "
            "ETA mode none means that you must not mention an ETA or time. "
            "Relative ETA must use the supplied minutes. "
            "Clock ETA must contain a time with a colon. "
            "Military ETA must contain a four-digit time. "
            "Informational and Unknown messages must not imply a response. "
            "Do not use a real name, phone number, address, coordinate, or URL. "
            "Do not add facts outside the request. Return JSON only."
        )
        payload = {
            "team_profiles": self._profile_summary({item.team for item in requests}),
            "requests": [
                {
                    "request_id": item.request_id,
                    "team": item.team,
                    "status": item.status,
                    "vehicle": item.vehicle,
                    "eta_mode": item.eta_mode,
                    **(
                        {"eta_minutes": item.eta_minutes}
                        if item.eta_mode == "relative"
                        else {}
                    ),
                    "message_type": item.message_type,
                }
                for item in requests
            ],
            "output": {
                "messages": [
                    {
                        "request_id": "string",
                        "text": "synthetic message",
                    }
                ]
            },
        }
        kwargs = {
            "model": self.deployment,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(payload, separators=(",", ":")),
                },
            ],
            "response_format": {"type": "json_object"},
            "max_completion_tokens": self.max_tokens,
            "reasoning_effort": self.reasoning_effort,
            "verbosity": self.verbosity,
        }
        try:
            response = self.client.chat.completions.create(**kwargs)
            content = str(response.choices[0].message.content or "")
            parsed = json.loads(content)
            values = parsed.get("messages")
            if not isinstance(values, list):
                raise ValueError("AI response does not contain a messages array")
            by_id = {
                str(item.get("request_id")): str(item.get("text") or "")
                for item in values
                if isinstance(item, dict)
            }
            usage = getattr(response, "usage", None)
            input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            latency = (time.perf_counter() - started) * 1000
            results: list[GeneratedMessage] = []
            for request in requests:
                raw_text = by_id.get(request.request_id, "")
                text = _strip_absence_markers(
                    sanitize_generated_text(raw_text)
                )
                error = None
                repair_reason = None
                if not text:
                    error = "missing_message"
                elif contains_pii(raw_text):
                    repair_reason = "pii_detected"
                elif any(ord(character) > 127 for character in raw_text):
                    repair_reason = "non_ascii_text"
                elif not _has_status_cue(text, request.status):
                    repair_reason = "status_control"
                elif (
                    request.status == "Responding"
                    and not _has_vehicle(text, request.vehicle)
                ):
                    repair_reason = "vehicle_control"
                elif (
                    request.status == "Responding"
                    and not has_eta_mode(text, request)
                ):
                    repair_reason = "eta_control"
                if repair_reason:
                    text = self.fallback.generate(request).text
                results.append(
                    GeneratedMessage(
                        request_id=request.request_id,
                        team=request.team,
                        status=request.status,
                        text=text,
                        strategy=self.name,
                        latency_ms=latency / len(requests),
                        input_tokens=input_tokens // len(requests),
                        output_tokens=output_tokens // len(requests),
                        error=error,
                        metadata={
                            "deployment": self.deployment,
                            "model_id": self.model_id,
                            "reasoning_effort": self.reasoning_effort,
                            "verbosity": self.verbosity,
                            "max_tokens": self.max_tokens,
                            "repaired_with": (
                                "heuristic" if repair_reason else None
                            ),
                            "repair_reason": repair_reason,
                        },
                    )
                )
            return results
        except Exception as exc:
            latency = (time.perf_counter() - started) * 1000
            return [
                GeneratedMessage(
                    request_id=request.request_id,
                    team=request.team,
                    status=request.status,
                    text="",
                    strategy=self.name,
                    latency_ms=latency / len(requests),
                    error=type(exc).__name__,
                    metadata={
                        "deployment": self.deployment,
                        "model_id": self.model_id,
                    },
                )
                for request in requests
            ]


def safe_profile_summary(
    profiles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = profiles or load_team_profiles()
    return {
        team: {
            "median_words": profile["median_words"],
            "p90_words": profile["p90_words"],
            "semantic_focus": profile["semantic_focus"],
            "common_vehicles": [
                vehicle
                for vehicle, _ in sorted(
                    profile["vehicle_counts"].items(),
                    key=lambda item: (-item[1], item[0]),
                )
                if vehicle != "Unknown"
            ][:4],
        }
        for team, profile in sorted(payload["teams"].items())
    }
