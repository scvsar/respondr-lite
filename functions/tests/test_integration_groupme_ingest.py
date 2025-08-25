import time
from typing import Dict, Any

import requests


def post_with_retries(url: str, payload: Dict[str, Any], headers: Dict[str, str],
                      attempts: int = 5, timeout: int = 10) -> requests.Response:
    backoff = 1
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            return resp
        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt == attempts:
                raise
            time.sleep(backoff)
            backoff = min(backoff * 2, 10)
    # Should not reach here, but raise to satisfy the type checker
    raise last_exc if last_exc is not None else RuntimeError("post_with_retries failed without raising")


def test_post_valid_groupme_message():
    #url = "https://respondrliteapp.azurewebsites.net/api/groupme_ingest?code=YOUR_FUNCTION_KEY_HERE"
    url = "http://localhost:7071/api/groupme_ingest"
    payload: Dict[str, Any] = {
        "attachments": [],
        "avatar_url": None,
        "created_at": 1755621705,
        "group_id": "12345567",
        "id": "0623dc16-a13c-412f-98d3-58ff073e20a3",
        "name": "Rudolf Carnap",
        "sender_id": "12345678",
        "sender_type": "user",
        "source_guid": "a8737e5e-fd69-41c1-b9ea-a37189613a8b",
        "system": False,
        "text": "Responding in my car, ETA 30 minutes",
        "user_id": "12345678",
    }

    headers = {"Content-Type": "application/json"}

    resp = post_with_retries(url, payload, headers, attempts=6, timeout=15)
    print(f"Response status: {resp.status_code}, body: {resp.text}")

    assert resp.status_code == 200, f"Unexpected status: {resp.status_code} body: {resp.text}"


if __name__ == "__main__":
    test_post_valid_groupme_message()
