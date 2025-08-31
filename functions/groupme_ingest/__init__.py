import logging
import os
import traceback
import urllib.request
import urllib.error

import azure.functions as func
from azure.storage.queue import QueueClient
from azure.core.exceptions import ResourceExistsError

from .schemas import GroupMeMessage
from pydantic import ValidationError

def main(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP trigger function that enqueues messages to Azure Storage Queue."""
    # Use Azure Functions built-in logging
    logging.info("Processing GroupMe webhook")
    logging.info("TEST debug log — function entered")
    logging.info(f"Request method: {req.method}")
    logging.info(f"Request URL: {req.url}")
    logging.info(f"Request headers: {dict(req.headers)}")
    logging.info(f"Request headers: {dict(req.headers)}")

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
        logging.info("Request JSON parsed; keys: %s", list(body.keys())[:10])
    except ValueError as e:
        logging.exception("Failed to parse JSON from request")
        return func.HttpResponse(f"Invalid JSON: {e}", status_code=400)
    

    # Validate payload against expected schema
    try:
        parsed: GroupMeMessage = GroupMeMessage.model_validate(body)  # pydantic v2
        logging.info("Payload validation succeeded; group_id=%s id=%s", parsed.group_id, parsed.id)
    except ValidationError as e:
        logging.warning("Payload validation failed: %s", str(e))
        return func.HttpResponse(f"Invalid payload: {e}", status_code=400)

    group_id = parsed.group_id

    # If no API key is set, require group_id in the payload and optionally validate it
    if not expected_key:
        if not group_id:
            logging.warning("Rejected request without group_id when no WEBHOOK_API_KEY configured")
            return func.HttpResponse("Unauthorized: missing group_id", status_code=401)
        if allowed_ids and group_id not in allowed_ids:
            logging.warning("Rejected request from disallowed group_id %s", group_id)
            return func.HttpResponse("Unauthorized: group not allowed", status_code=401)


    queue_name = os.getenv("STORAGE_QUEUE_NAME")
    logging.info(queue_name)
    conn_str = os.getenv("AzureWebJobsStorage")
    if not queue_name or not conn_str:
        logging.error("Missing queue configuration")
        return func.HttpResponse("Server error", status_code=500)

    try:
        # check if queue exists and if not, create it
        queue = QueueClient.from_connection_string(conn_str, queue_name)
        try:
            r = queue.create_queue()
            print(r)
        except ResourceExistsError:
            pass  # Queue already exists
        logging.info("Sending message to queue '%s'", queue_name)
        
        # Serialize the GroupMeMessage to JSON using Pydantic's built-in method
        message_json = parsed.model_dump_json()
        logging.info("Serialized message: %s", message_json)
        
        try:
            queue.send_message(message_json)
            logging.info("Successfully sent message to queue")
        except Exception as e:
            logging.error("Failed to send message to queue: %s", e)
            raise
        
        # Wake up the container app if configured
        wake_url = os.getenv("CONTAINER_APP_WAKE_URL")
        if wake_url:
            try:
                logging.info(f"Waking container app at: {wake_url}")
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
                logging.warning(f"Failed to wake container app: {e}")
            except Exception as e:
                logging.warning(f"Unexpected error waking container app: {e}")
        else:
            logging.info("CONTAINER_APP_WAKE_URL not configured, skipping wake request")
            
        return func.HttpResponse("OK", status_code=200)       
    except Exception as e:
        # Log full traceback and return exception type+message for local debugging
        logging.error("Failed to send message to queue: %s", e)
        logging.error(traceback.format_exc())
        return func.HttpResponse(f"Queue error: {type(e).__name__}: {e}", status_code=500)
