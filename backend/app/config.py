<<<<<<< HEAD
"""Configuration module for Respondr backend.

Handles all environment variables, constants, and global configuration.
Provides timezone handling and basic logging setup.
"""

import os
import sys
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Timezone handling
try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    zoneinfo_available = True
except ImportError:
    zoneinfo_available = False
    _ZoneInfo = None

def get_timezone(name: str) -> timezone:
    """Get timezone object with fallback for systems without zoneinfo."""
    if name == "UTC":
        return timezone.utc
    elif name == "America/Los_Angeles" and zoneinfo_available:
        try:
            return _ZoneInfo("America/Los_Angeles")  # type: ignore
        except Exception:
            pass
    # Fallback: PST approximation (no DST) if zoneinfo unavailable
    return timezone(timedelta(hours=-8))

TIMEZONE = os.getenv("TIMEZONE", "America/Los_Angeles")
APP_TZ = get_timezone(TIMEZONE)

# Warn about timezone fallback
if not zoneinfo_available and TIMEZONE.upper() != "UTC":
    logger.warning(
        "zoneinfo not available; using fixed UTC-8 fallback. "
        "Set TIMEZONE=UTC or install zoneinfo for correct DST."
    )

def now_tz() -> datetime:
    """Get current time in the configured timezone."""
    return datetime.now(APP_TZ)


# Redis configuration
REDIS_HOST = os.getenv("REDIS_HOST", "redis-service")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_KEY = "respondr_messages"
REDIS_DELETED_KEY = "respondr_deleted_messages"

# Authentication and authorization
webhook_api_key = os.getenv("WEBHOOK_API_KEY")
allowed_email_domains = [
    d.strip() 
    for d in os.getenv("ALLOWED_EMAIL_DOMAINS", "scvsar.org,rtreit.com").split(",") 
    if d.strip()
]
allowed_admin_users = [
    u.strip().lower() 
    for u in os.getenv("ALLOWED_ADMIN_USERS", "").split(",") 
    if u.strip()
]

ALLOW_LOCAL_AUTH_BYPASS = os.getenv("ALLOW_LOCAL_AUTH_BYPASS", "false").lower() == "true"
LOCAL_BYPASS_IS_ADMIN = os.getenv("LOCAL_BYPASS_IS_ADMIN", "false").lower() == "true"

# Testing and development flags
is_testing = os.getenv("PYTEST_CURRENT_TEST") is not None or "pytest" in sys.modules
disable_api_key_check = (
    os.getenv("DISABLE_API_KEY_CHECK", "false").lower() == "true" or is_testing
)

# Temporary override for PoC
disable_api_key_check = True

# Azure OpenAI configuration
azure_openai_api_key = os.getenv("AZURE_OPENAI_API_KEY")
azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
azure_openai_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
azure_openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION")

# Debug flags
DEBUG_LOG_HEADERS = os.getenv("DEBUG_LOG_HEADERS", "false").lower() == "true"
DEBUG_FULL_LLM_LOG = os.getenv("DEBUG_FULL_LLM_LOG", "").lower() in ("1", "true", "yes")

# ACR webhook configuration
ACR_WEBHOOK_TOKEN = os.getenv("ACR_WEBHOOK_TOKEN")
K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "respondr")
K8S_DEPLOYMENT = os.getenv("K8S_DEPLOYMENT", "respondr-deployment")

# GroupMe Group ID to Team mapping
GROUP_ID_TO_TEAM: Dict[str, str] = {
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
=======
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
>>>>>>> ef84adee5db2588b7c1441dfc10679fb2b09f3e0
