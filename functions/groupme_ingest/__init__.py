import logging
import os
import urllib.request
import urllib.error
from typing import Optional

import azure.functions as func
from azure.storage.queue import QueueClient
from azure.core.exceptions import ResourceExistsError

from .schemas import GroupMeMessage
from .payload_logger import log_payload
from pydantic import ValidationError


def _get_queue_api_version(conn_str: str) -> Optional[str]:
    """Return an explicit queue API version when needed (primarily for Azurite)."""
    explicit_version = os.getenv("AZURE_STORAGE_QUEUE_API_VERSION", "").strip()
    if explicit_version:
        return explicit_version

    lowered = conn_str.lower()
    is_azurite = (
        "devstoreaccount1" in lowered
        or "127.0.0.1:10001" in lowered
        or "localhost:10001" in lowered
        or "azurite:10001" in lowered
    )
    if is_azurite:
        return "2021-12-02"

    return None

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

    if not expected_key and not allowed_ids:
        logging.error("Webhook authentication policy is not configured")
        return func.HttpResponse("Webhook unavailable", status_code=503)

    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse("Invalid JSON", status_code=400)

    try:
        parsed = GroupMeMessage.model_validate(body)
    except ValidationError:
        return func.HttpResponse("Invalid payload", status_code=400)

    group_id = parsed.group_id

    # If no API key is set, require group_id in the payload and optionally validate it
    if not expected_key:
        if not group_id:
            logging.warning("Rejected request without group_id when no WEBHOOK_API_KEY configured")
            return func.HttpResponse("Unauthorized: missing group_id", status_code=401)
        if allowed_ids and group_id not in allowed_ids:
            logging.warning("Rejected request from disallowed group_id %s", group_id)
            return func.HttpResponse("Unauthorized: group not allowed", status_code=401)


    # Preserve only validated, authorized payloads. Never persist authentication headers.
    log_payload(parsed.model_dump(), None, req.method)


    queue_name = os.getenv("STORAGE_QUEUE_NAME")
    logging.info(queue_name)
    conn_str = os.getenv("AzureWebJobsStorage")
    if not queue_name or not conn_str:
        logging.error("Missing queue configuration")
        return func.HttpResponse("Server error", status_code=500)

    try:
        # check if queue exists and if not, create it
        queue_api_version = _get_queue_api_version(conn_str)
        queue_options = {"connection_timeout": 3, "read_timeout": 5, "retry_total": 1}
        if queue_api_version:
            logging.info("Using queue API version %s", queue_api_version)
            queue = QueueClient.from_connection_string(
                conn_str,
                queue_name,
                api_version=queue_api_version,
                **queue_options,
            )
        else:
            queue = QueueClient.from_connection_string(conn_str, queue_name, **queue_options)
        try:
            queue.create_queue()
        except ResourceExistsError:
            pass  # Queue already exists
        logging.info("Sending message to queue '%s'", queue_name)
        
        # Serialize the GroupMeMessage to JSON using Pydantic's built-in method
        message_json = parsed.model_dump_json()
        
        try:
            queue.send_message(message_json)
            logging.info("Successfully sent message to queue")
        except Exception as e:
            logging.error("Failed to send message to queue")
            raise
        
        # Wake up the container app if configured
        wake_url = os.getenv("CONTAINER_APP_WAKE_URL")
        if wake_url:
            try:
                logging.info("Waking container app")
                wake_req = urllib.request.Request(wake_url, method='GET')
                wake_req.add_header('User-Agent', 'Azure-Function-Wake-Request')
                
                # Short timeout since we just want to trigger the wake
                with urllib.request.urlopen(wake_req, timeout=5) as response:
                    if response.status == 200:
                        logging.info("Container app wake request successful")
                    else:
                        logging.warning(f"Container app wake request returned status: {response.status}")
            except urllib.error.URLError as e:
                # Log but don't fail - the container might already be awake
                logging.warning("Failed to wake container app")
            except Exception as e:
                logging.warning("Unexpected error waking container app")
        else:
            logging.info("CONTAINER_APP_WAKE_URL not configured, skipping wake request")
            
        return func.HttpResponse("OK", status_code=200)       
    except Exception as e:
        logging.error("Failed to send message to queue")
        return func.HttpResponse("Queue unavailable", status_code=500)
