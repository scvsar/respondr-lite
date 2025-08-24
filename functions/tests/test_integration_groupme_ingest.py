import json
import time
from typing import Dict, Any

import requests


def post_with_retries(url: str, payload: Dict[str, Any], headers: Dict[str, str],
                      attempts: int = 5, timeout: int = 10) -> requests.Response:
    backoff = 1
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            return resp
        except requests.exceptions.RequestException as e:
            if attempt == attempts:
                raise
            time.sleep(backoff)
            backoff = min(backoff * 2, 10)


def test_post_valid_groupme_message():
    url = "http://localhost:7071/api/groupme_ingest"
    payload = {
        "attachments": [],
        "avatar_url": None,
        "created_at": 1755621705,
        "group_id": "16649586",
        "id": "48aa762a-ed4c-4391-8877-1850034c6642",
        "name": "Lucas Kutsick",
        "sender_id": "45820359",
        "sender_type": "user",
        "source_guid": "d0ac1d5a-73db-4786-b7d6-d870abaeaf3f",
        "system": False,
        "text": "10-22 standing down ",
        "user_id": "45820359",
    }

    headers = {"Content-Type": "application/json"}

    resp = post_with_retries(url, payload, headers, attempts=6, timeout=15)

    assert resp.status_code == 200, f"Unexpected status: {resp.status_code} body: {resp.text}"


if __name__ == "__main__":
    test_post_valid_groupme_message()