"""Utility script for sending test GroupMe-style payloads to the webhook."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from typing import Any, Dict

import requests


DEFAULT_URL = (
	"https://respondrliteapp-ad473d76.azurewebsites.net/api/"
	"groupme_ingest?code=<code goes here>"
)


def build_payload(args: argparse.Namespace) -> Dict[str, Any]:
	"""Construct the GroupMe-style payload expected by the Azure Function."""

	created_at = int(time.time())
	return {
		"attachments": [],
		"avatar_url": args.avatar_url,
		"created_at": created_at,
		"group_id": args.group_id,
		"id": args.message_id,
		"name": args.name,
		"sender_id": args.sender_id,
		"sender_type": "user",
		"source_guid": args.source_guid,
		"system": False,
		"text": args.text,
		"user_id": args.user_id,
	}


def send_payload(url: str, payload: Dict[str, Any], timeout: float = 30.0) -> requests.Response:
	"""Send the payload and return the HTTP response."""

	response = requests.post(url, json=payload, timeout=timeout)
	return response


def dump_response(response: requests.Response) -> None:
	"""Pretty-print the HTTP status and body for quick inspection."""

	print(f"Status: {response.status_code}")
	try:
		parsed = response.json()
		formatted = json.dumps(parsed, indent=2)
		print("Body (JSON):")
		print(formatted)
	except ValueError:
		print("Body (raw):")
		print(response.text)


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--url", default=DEFAULT_URL, help="Webhook endpoint to call")
	parser.add_argument("--group-id", default="102193274", help="GroupMe group identifier")
	parser.add_argument("--name", default="Test Responder", help="Display name of the sender")
	parser.add_argument("--text", default="Responding POV ETA 25", help="Message text to send")
	parser.add_argument("--avatar-url", default="https://i.groupme.com/123x123.jpeg.12345678")
	parser.add_argument("--message-id", default="999999999999999999")
	parser.add_argument("--sender-id", default="123456789012345678")
	parser.add_argument("--user-id", default="123456789012345678")
	parser.add_argument(
		"--source-guid",
		default=None,
		help="Source GUID for the message (defaults to a random UUID)",
	)
	parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds")
	args = parser.parse_args()
	if not args.source_guid:
		args.source_guid = str(uuid.uuid4())
	return args


def main() -> None:
	args = parse_args()
	payload = build_payload(args)
	print("Sending payload:")
	print(json.dumps(payload, indent=2))

	response = send_payload(args.url, payload, timeout=args.timeout)
	dump_response(response)


if __name__ == "__main__":
	main()