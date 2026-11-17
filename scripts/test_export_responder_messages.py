"""Test the export without a storage account or a repository .env file."""

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts import export_responder_messages as export


class ExportResponderMessagesTests(unittest.TestCase):
    def test_dotenv_and_environment_precedence(self):
        with TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(f"{export.KEY_ENV}=sample-file-key\n", encoding="utf-8")
            for environment, expected_key in (
                ({}, "sample-file-key"),
                ({export.KEY_ENV: "sample-env-key"}, "sample-env-key"),
            ):
                with (
                    self.subTest(environment=environment),
                    patch.dict(os.environ, environment, clear=True),
                    patch.object(export, "ENV_FILE", env_file),
                    patch.object(export, "TableClient") as client,
                    patch.object(export, "datetime", wraps=datetime) as clock,
                    patch("sys.argv", ["export_responder_messages.py", "--days", "14"]),
                    redirect_stdout(io.StringIO()) as output,
                ):
                    clock.now.return_value = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
                    table = client.return_value.__enter__.return_value
                    table.list_entities.return_value = [
                        {"RowKey": "recent", "timestamp_utc": "2026-11-04T12:00:00Z"},
                        {"RowKey": "older", "timestamp_utc": "2026-11-02T12:00:00Z"},
                    ]

                    export.main()

                    credential = client.call_args.kwargs["credential"]
                    self.assertEqual(credential.named_key.key, expected_key)
                    self.assertEqual(json.loads(output.getvalue())["RowKey"], "recent")
