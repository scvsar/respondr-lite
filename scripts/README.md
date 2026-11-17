# Export Responder Messages

The export tool reads raw rows from an Azure Storage table. Use Python 3.11 or later.
Run these commands from the repository root.

1. Install the dependencies.

   ```powershell
   python -m pip install azure-data-tables python-dotenv tzdata
   ```

2. Add these settings to the `.env` file in the repository root.
   Replace each placeholder with the value for the deployment to export.

   ```dotenv
   RESPONDR_STORAGE_ACCOUNT_NAME=YOUR_STORAGE_ACCOUNT_NAME
   RESPONDR_STORAGE_ACCOUNT_KEY=YOUR_STORAGE_ACCOUNT_KEY
   RESPONDR_STORAGE_TABLE_NAME=YOUR_RESPONDER_TABLE_NAME
   RESPONDR_MESSAGE_TIMEZONE=YOUR_IANA_TIME_ZONE
   ```

   Use the deployment's IANA time zone for older messages with no UTC offset.
   An environment variable takes precedence over the same setting in `.env`.

3. Run the export.

   ```powershell
   python .\scripts\export_responder_messages.py --days 14 > responder-messages.jsonl
   ```

The tool uses a seven-day window if you omit `--days`. It writes one JSON object per line.
The tool filters by message time and includes matching soft-deleted rows.
Keep the key and the export file private.
