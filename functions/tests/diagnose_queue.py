import os
import json
import sys
import traceback

from azure.storage.queue import QueueClient


def main():
    conn_str = os.getenv("AzureWebJobsStorage")
    queue_name = os.getenv("STORAGE_QUEUE_NAME")

    if not conn_str:
        print("AzureWebJobsStorage not set in environment")
        sys.exit(2)
    if not queue_name:
        print("STORAGE_QUEUE_NAME not set in environment")
        sys.exit(2)

    print("Attempting to connect to queue:", queue_name)
    try:
        queue = QueueClient.from_connection_string(conn_str, queue_name)
        res = queue.send_message(json.dumps({"test": "ping"}))
        print("Message enqueued. Response:", res)
    except Exception as e:
        print("Queue operation failed:")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
