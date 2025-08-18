import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests


@dataclass
class Config:
    url: str
    api_key: Optional[str]
    group_id: str
    name: str
    delay_ms: int
    cases_path: str
    modes: List[str]


def _parse_iso_utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def _to_epoch(dt_utc: datetime) -> int:
    return int(dt_utc.timestamp())


def _payload(name: str, text: str, created_at: int, group_id: str) -> Dict[str, Any]:
    """Build a minimal GroupMe-like payload expected by /webhook."""
    return {
        "attachments": [],
        "avatar_url": "https://i.groupme.com/placeholder.jpeg",
        "created_at": created_at,
        "group_id": group_id,
        "id": str(created_at),
        "name": name,
        "sender_id": "bench",
        "sender_type": "user",
        "source_guid": str(created_at),
        "system": False,
        "text": text,
        "user_id": "bench",
    }


def _with_mode(url: str, mode: str) -> str:
    sep = '&' if ('?' in url) else '?'
    return f"{url}{sep}mode={mode}"


def post_case(cfg: Config, session: requests.Session, url: str, name: str, text: str, created_at: int) -> requests.Response:
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["X-API-Key"] = cfg.api_key
    body = _payload(name, text, created_at, cfg.group_id)
    return session.post(url, data=json.dumps(body), headers=headers, timeout=15)


def main():
    ap = argparse.ArgumentParser(description="Post benchmark SAR test cases to /webhook")
    ap.add_argument("--url", default=os.getenv("WEBHOOK_URL", "http://localhost:8000/webhook"))
    ap.add_argument("--api-key", default=os.getenv("WEBHOOK_API_KEY"))
    ap.add_argument("--group-id", default=os.getenv("GROUP_ID", "102193274"))
    ap.add_argument("--name", default=os.getenv("BENCH_NAME", "Benchmark User"))
    ap.add_argument("--delay-ms", type=int, default=int(os.getenv("BENCH_DELAY_MS", "100") or 100))
    ap.add_argument(
        "--cases",
        default=os.getenv("BENCH_CASES", os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "benchmark", "sar_test_cases.json")),
    )
    ap.add_argument("--modes", default=os.getenv("BENCH_MODES", "llm-only,assisted"), help="Comma-separated: raw|assisted|llm-only (raw is rules-only)")
    args = ap.parse_args()

    modes = [m.strip().lower() for m in str(args.modes).split(',') if m.strip()]
    cfg = Config(
        url=args.url,
        api_key=args.api_key,
        group_id=args.group_id,
        name=args.name,
        delay_ms=args.delay_ms,
        cases_path=os.path.abspath(args.cases),
        modes=modes,
    )

    with open(cfg.cases_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("meta", {})
    base_iso = meta.get("baseTime") or "2024-01-01T00:00:00Z"
    base_dt_utc = _parse_iso_utc(base_iso)
    cases: List[Dict[str, Any]] = data.get("cases", [])

    s = requests.Session()
    sent = 0
    for i, case in enumerate(cases, start=1):
        text: str = case.get("input", "")
        cur_iso: Optional[str] = case.get("currentTimeStamp")
        base_override: Optional[str] = case.get("baseTimeOverride")  # like "23:50"
        prev_eta_iso: Optional[str] = case.get("prevETA")

        # Determine message time in UTC for this case
        if cur_iso:
            msg_dt_utc = _parse_iso_utc(cur_iso)
        elif base_override:
            # Replace time on the base date with override HH:MM
            hh, mm = map(int, base_override.split(":"))
            msg_dt_utc = base_dt_utc.replace(hour=hh, minute=mm, second=0, microsecond=0)
        else:
            # Default: use suite base time
            msg_dt_utc = base_dt_utc
        # Ensure uniqueness by adding i seconds
        msg_dt_utc = msg_dt_utc + timedelta(seconds=(i - 1))

        try:
            created_at = _to_epoch(msg_dt_utc)
            for mode in cfg.modes:
                # Friendly label
                label = ("LLM" if mode in ("llm-only", "llm", "ai-only") else ("Assist" if mode.startswith("assist") else "Raw"))
                name_mode = f"{cfg.name} [{label}]"
                url_mode = _with_mode(cfg.url, ("llm-only" if mode in ("llm-only","llm","ai-only") else ("assisted" if mode.startswith("assist") else "raw")))

                # Seed prevETA context per mode name so the two runs don't influence each other
                if prev_eta_iso:
                    prev_eta_dt_utc = _parse_iso_utc(prev_eta_iso)
                    prev_eta_hhmm = prev_eta_dt_utc.strftime("%H:%M")
                    prior_created_at = created_at - 60
                    r_prior = post_case(cfg, s, url_mode, name_mode, f"ETA {prev_eta_hhmm}", prior_created_at)
                    print(f"[{i:02d} {label} seed prevETA] {r_prior.status_code} {r_prior.text[:120]}…")

                r = post_case(cfg, s, url_mode, name_mode, text, created_at)
                sent += 1 if r.ok else 0
                print(f"[{i:02d} {label}] {r.status_code} {r.text[:200]}…")

                # Gentle pacing between modes
                if cfg.delay_ms > 0:
                    time.sleep(cfg.delay_ms / 1000.0)
        finally:
            # Gentle pacing between cases
            if cfg.delay_ms > 0:
                time.sleep(cfg.delay_ms / 1000.0)

    print(f"Done. Sent {sent}/{len(cases)} cases to {cfg.url}")


if __name__ == "__main__":
    main()
