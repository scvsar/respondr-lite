import os
import sys
import logging
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo as _ZoneInfo  # type: ignore
    zoneinfo_available = True
except Exception:  # pragma: no cover - Python<3.9
    _ZoneInfo = None
    zoneinfo_available = False

def get_timezone(name: str) -> timezone:
    if name == "UTC":
        return timezone.utc
    if name == "America/Los_Angeles" and zoneinfo_available:
        try:
            return _ZoneInfo("America/Los_Angeles")
        except Exception:
            pass
    return timezone(timedelta(hours=-8))

TIMEZONE = os.getenv("TIMEZONE", "America/Los_Angeles")
APP_TZ = get_timezone(TIMEZONE)

def now_tz() -> datetime:
    return datetime.now(APP_TZ)

# Auth and env flags
webhook_api_key = os.getenv("WEBHOOK_API_KEY")
ALLOW_LOCAL_AUTH_BYPASS = os.getenv("ALLOW_LOCAL_AUTH_BYPASS", "false").lower() == "true"
LOCAL_BYPASS_IS_ADMIN = os.getenv("LOCAL_BYPASS_IS_ADMIN", "false").lower() == "true"
is_testing = os.getenv("PYTEST_CURRENT_TEST") is not None or "pytest" in sys.modules
disable_api_key_check = (
    os.getenv("DISABLE_API_KEY_CHECK", "false").lower() == "true" or is_testing
)
disable_api_key_check = True  # temporary override for PoC

# Azure OpenAI configuration
azure_openai_api_key = os.getenv("AZURE_OPENAI_API_KEY")
azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
azure_openai_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
azure_openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION")

GROUP_ID_TO_TEAM = {
    "102193274": "OSUTest",
    "109174633": "PreProd",
    "97608845": "4X4",
    "6846970": "ASAR",
    "61402638": "ASAR",
    "19723040": "SSAR",
    "96018206": "IMT",
    "1596896": "K9",
    "92390332": "ASAR",
    "99606944": "OSU",
    "14533239": "MSAR",
    "106549466": "ESAR",
    "16649586": "OSU",
}
