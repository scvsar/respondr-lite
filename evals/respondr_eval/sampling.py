"""Read-only production sampling for local human annotation."""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .dataset import write_jsonl
from .schema import EvalCase, ReferenceLabel, normalize_eta_iso, normalize_status, normalize_vehicle
from .strategies.heuristic import HeuristicStrategy


def _hash(value: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()[:16]


def _safe_label(entity: dict[str, Any]) -> ReferenceLabel:
    try:
        status = normalize_status(entity.get("raw_status") or entity.get("arrival_status"))
    except ValueError:
        status = "Unknown"
    try:
        vehicle = normalize_vehicle(entity.get("vehicle"))
    except ValueError:
        vehicle = "Unknown"
    try:
        eta = normalize_eta_iso(
            entity.get("eta_timestamp_utc") or entity.get("eta_timestamp")
        )
    except ValueError:
        eta = "Unknown"
    if status in {"Cancelled", "Not Responding"}:
        eta = "Unknown"
    return ReferenceLabel(status=status, vehicle=vehicle, eta_iso=eta)


def _created_at(entity: dict[str, Any]) -> int:
    try:
        return int(entity.get("created_at") or 0)
    except (TypeError, ValueError):
        return 0


def _base_time(entity: dict[str, Any]) -> str:
    epoch = _created_at(entity)
    if epoch > 0:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
    timestamp = entity.get("timestamp_utc") or entity.get("timestamp")
    if timestamp:
        try:
            parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            if parsed.tzinfo:
                return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            pass
    raise ValueError(f"Entity {entity.get('RowKey', '<unknown>')} has no valid timestamp")


def _query_entities(account_name: str, table_name: str) -> list[dict[str, Any]]:
    azure_cli = shutil.which("az") or shutil.which("az.cmd")
    if not azure_cli:
        raise RuntimeError("Azure CLI is not installed or is not on PATH")
    entities: list[dict[str, Any]] = []
    marker: dict[str, str] | None = None
    while True:
        command = [
            azure_cli,
            "storage",
            "entity",
            "query",
            "--account-name",
            account_name,
            "--auth-mode",
            "key",
            "--table-name",
            table_name,
            "--filter",
            "PartitionKey eq 'messages'",
            "--num-results",
            "1000",
            "--output",
            "json",
        ]
        if marker:
            command.extend(
                [
                    "--marker",
                    f"nextpartitionkey={marker['nextpartitionkey']}",
                    f"nextrowkey={marker['nextrowkey']}",
                ]
            )
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if completed.returncode:
            detail = (
                completed.stderr.strip().splitlines()[-1]
                if completed.stderr
                else "unknown error"
            )
            raise RuntimeError(f"Azure Table query failed: {detail}")
        payload = json.loads(completed.stdout)
        entities.extend(payload.get("items") or [])
        marker = payload.get("nextMarker")
        if not marker:
            return entities


def _salt(path: Path) -> str:
    salt_path = path.parent / ".sampling_salt"
    if salt_path.exists():
        return salt_path.read_text(encoding="utf-8").strip()
    value = secrets.token_hex(32)
    salt_path.parent.mkdir(parents=True, exist_ok=True)
    salt_path.write_text(value + "\n", encoding="utf-8")
    return value


def sample_production(
    account_name: str,
    table_name: str,
    output_path: str | Path,
    max_cases: int = 0,
) -> dict[str, Any]:
    output = Path(output_path).resolve()
    entities = sorted(_query_entities(account_name, table_name), key=_created_at)
    salt = _salt(output)
    heuristic = HeuristicStrategy()
    history: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    mission_state: dict[str, dict[str, Any]] = {}
    cases: list[EvalCase] = []
    retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    for entity in entities:
        text = str(entity.get("text") or "").strip()
        source_id = str(entity.get("RowKey") or entity.get("groupme_id") or "")
        if not text or not source_id:
            continue
        sender = str(entity.get("name") or "")
        group = str(entity.get("group_id") or "unknown")
        created_at = _created_at(entity)
        current_mission = mission_state.get(group)
        if (
            current_mission is None
            or created_at - int(current_mission["last_created_at"]) > 12 * 3600
        ):
            current_mission = {
                "key": f"{group}:{created_at}",
                "last_created_at": created_at,
            }
            mission_state[group] = current_mission
        else:
            current_mission["last_created_at"] = created_at
        history_key = (group, sender.lower())
        base_time = _base_time(entity)
        prior = [
            item
            for item in history[history_key]
            if _created_at(entity) - item["created_at"] <= 12 * 3600
        ][-5:]
        production = _safe_label(entity)
        previous_eta = next(
            (
                item["eta_timestamp_utc"]
                for item in reversed(prior)
                if item.get("status") == "Responding"
                and item.get("eta_timestamp_utc") != "Unknown"
            ),
            None,
        )
        case = EvalCase(
            case_id=f"prod-{_hash(source_id, salt)}",
            split="unassigned",
            input={
                "text": text,
                "base_time": base_time,
                "previous_eta_iso": previous_eta,
                "previous_messages": [
                    {
                        "text": item["text"],
                        "timestamp": item["timestamp"],
                        "status": item["status"],
                        "vehicle": item["vehicle"],
                        "eta": item["eta"],
                    }
                    for item in prior
                ],
            },
            reference=production,
            annotation={
                "state": "proposed",
                "reviewer": None,
                "notes": "",
                "proposal_source": "pending",
                "review_priority": 0,
            },
            provenance={
                "source": "azure_table",
                "source_id": source_id,
                "storage_account": account_name,
                "table": table_name,
                "group_hash": _hash(group, salt),
                "mission_hash": _hash(str(current_mission["key"]), salt),
                "responder_hash": _hash(sender, salt),
                "retrieved_at": retrieved_at,
            },
            observations={"production": production.to_dict()},
        )
        suggested = heuristic.predict(case)
        case.observations["heuristic"] = {
            "status": suggested.status,
            "vehicle": suggested.vehicle,
            "eta_iso": suggested.eta_iso,
            "confidence": suggested.confidence,
            "reasons": suggested.metadata,
        }

        proposal = production.to_dict()
        proposal_source: list[str] = []
        if suggested.confidence is not None and suggested.confidence >= 0.8:
            proposal["status"] = suggested.status
            proposal_source.append("heuristic-status")
        if suggested.vehicle != "Unknown":
            proposal["vehicle"] = suggested.vehicle
            proposal_source.append("heuristic-vehicle")
        if suggested.eta_iso != "Unknown":
            proposal["eta_iso"] = suggested.eta_iso
            proposal_source.append("heuristic-eta")
        if proposal["status"] in {"Cancelled", "Not Responding"}:
            proposal["eta_iso"] = "Unknown"
        case.reference = ReferenceLabel.from_dict(proposal)

        disagreements = sum(
            case.reference.to_dict()[field] != production.to_dict()[field]
            for field in ("status", "vehicle", "eta_iso")
        )
        unknowns = sum(
            value == "Unknown" for value in case.reference.to_dict().values()
        )
        case.annotation["proposal_source"] = (
            ",".join(proposal_source) if proposal_source else "production"
        )
        case.annotation["review_priority"] = disagreements * 10 + unknowns
        cases.append(case)

        history[history_key].append(
            {
                "created_at": _created_at(entity),
                "text": text,
                "timestamp": str(entity.get("timestamp") or base_time),
                "status": production.status,
                "vehicle": production.vehicle,
                "eta": str(entity.get("eta") or "Unknown"),
                "eta_timestamp_utc": production.eta_iso,
            }
        )

    cases.sort(
        key=lambda item: (
            -int(item.annotation.get("review_priority", 0)),
            item.input["base_time"],
            item.case_id,
        )
    )
    if max_cases > 0:
        cases = cases[:max_cases]
    write_jsonl(output, cases)
    return {
        "source_entities": len(entities),
        "candidate_cases": len(cases),
        "output": str(output),
        "retrieved_at": retrieved_at,
    }
