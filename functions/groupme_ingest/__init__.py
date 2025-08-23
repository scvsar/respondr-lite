import json
import logging
import os

import azure.functions as func
from azure.storage.queue import QueueClient
from dotenv import load_dotenv

# Load environment variables from .env for local testing
load_dotenv()


def main(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP trigger function that enqueues messages to Azure Storage Queue."""
    logging.info("Processing GroupMe webhook")

    expected_key = os.getenv("WEBHOOK_API_KEY", "")
    k_param = req.params.get("k", None)
    
    # Get header token using a type-safe approach
    header_token: str | None = None
    try:
        if req.headers and "X-Webhook-Token" in req.headers:
            header_value = req.headers["X-Webhook-Token"]
            header_token = str(header_value) if header_value else None
    except (KeyError, TypeError):
        header_token = None
    
    token = str(k_param) if k_param is not None else header_token if header_token is not None else ""

    # Initialize allowed_ids to avoid unbound variable issue
    allowed_ids: list[str] = []
    
    # If a webhook API key is configured, require it (either via ?k= or X-Webhook-Token)
    if expected_key:
        if token != expected_key:
            return func.HttpResponse("Unauthorized", status_code=401)
    else:
        # No API key configured. Restrict by GroupMe group id to avoid open endpoint.
        # Optionally set ALLOWED_GROUPME_GROUP_IDS as a comma-separated list of allowed group ids.
        allowed = os.getenv("ALLOWED_GROUPME_GROUP_IDS", "")
        allowed_ids = [g.strip() for g in allowed.split(",") if g.strip()]

    try:
        body = req.get_json()
    except ValueError as e:
        logging.exception("Failed to parse JSON from request")
        return func.HttpResponse(f"Invalid JSON: {e}", status_code=400)

    group_id = body.get("group_id")

    # If no API key is set, require group_id in the payload and optionally validate it
    if not expected_key:
        if not group_id:
            logging.warning("Rejected request without group_id when no WEBHOOK_API_KEY configured")
            return func.HttpResponse("Unauthorized: missing group_id", status_code=401)
        if allowed_ids and group_id not in allowed_ids:
            logging.warning("Rejected request from disallowed group_id %s", group_id)
            return func.HttpResponse("Unauthorized: group not allowed", status_code=401)

    message = {
        "name": body.get("name"),
        "text": body.get("text"),
        "created_at": body.get("created_at"),
        "group_id": group_id,
    }

    queue_name = os.getenv("STORAGE_QUEUE_NAME")
    conn_str = os.getenv("AzureWebJobsStorage")
    if not queue_name or not conn_str:
        logging.error("Missing queue configuration")
        return func.HttpResponse("Server error", status_code=500)

    try:
        queue = QueueClient.from_connection_string(conn_str, queue_name)
        queue.send_message(json.dumps(message))
    except Exception as e:
        logging.exception("Failed to send message to queue")
        return func.HttpResponse(f"Queue error: {e}", status_code=500)

    return func.HttpResponse("OK", status_code=200)
