from typing import List
from fastapi import APIRouter

router = APIRouter()

@router.get("/api/responders")
async def get_responders() -> List[dict]:
    import main  # type: ignore
    return main.messages
