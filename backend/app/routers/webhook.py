from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends

from ..auth import validate_webhook_api_key
from ..config import APP_TZ, GROUP_ID_TO_TEAM
from ..llm import extract_details_from_text
from ..storage import save_messages

router = APIRouter()

@router.post("/webhook")
async def webhook(payload: Dict[str, Any], _: bool = Depends(validate_webhook_api_key)) -> Dict[str, str]:
    name = payload.get("name") or "Unknown"
    text = payload.get("text") or ""
    created_at = payload.get("created_at")
    group_id = str(payload.get("group_id")) if payload.get("group_id") else None
    message_time = datetime.fromtimestamp(created_at, tz=APP_TZ) if created_at else datetime.now(tz=APP_TZ)
    parsed = extract_details_from_text(text, base_time=message_time)
    msg: Dict[str, Any] = {
        "id": payload.get("id") or payload.get("source_guid"),
        "name": name,
        "text": text,
        "timestamp": message_time.strftime("%Y-%m-%d %H:%M:%S"),
        "timestamp_utc": message_time.astimezone(timezone.utc).isoformat(),
        "vehicle": parsed["vehicle"],
        "eta": parsed["eta"],
        "eta_timestamp": parsed["eta_timestamp"],
        "eta_timestamp_utc": parsed["eta_timestamp_utc"],
        "minutes_until_arrival": parsed["minutes_until_arrival"],
        "arrival_status": parsed["raw_status"],
        "parse_source": parsed["parse_source"],
    }
    if group_id and group_id in GROUP_ID_TO_TEAM:
        msg["team"] = GROUP_ID_TO_TEAM[group_id]
    import main  # type: ignore
    main.messages.append(msg)
    save_messages()
    return {"status": "ok"}
