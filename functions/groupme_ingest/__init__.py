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
    token = req.params.get("k") or req.headers.get("X-Webhook-Token")
    if expected_key and token != expected_key:
        return func.HttpResponse("Unauthorized", status_code=401)

    try:
        body = req.get_json()
    except ValueError as e:
        logging.exception("Failed to parse JSON from request")
        return func.HttpResponse(f"Invalid JSON: {e}", status_code=400)

    message = {
        "name": body.get("name"),
        "text": body.get("text"),
        "created_at": body.get("created_at"),
        "group_id": body.get("group_id"),
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
