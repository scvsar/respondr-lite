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

# Azure OpenAI configuration
azure_openai_api_key = os.getenv("AZURE_OPENAI_API_KEY")
azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
azure_openai_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
azure_openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION")

# Debug flags
DEBUG_LOG_HEADERS = os.getenv("DEBUG_LOG_HEADERS", "false").lower() == "true"
DEBUG_FULL_LLM_LOG = os.getenv("DEBUG_FULL_LLM_LOG", "").lower() in ("1", "true", "yes")

# LLM token configuration (defaults with env overrides)
# Default number of completion tokens to request from the model, unless overridden per-request
DEFAULT_MAX_COMPLETION_TOKENS = int(os.getenv("MAX_COMPLETION_TOKENS", "1024"))
# Minimum allowed when clamping user overrides or internal adjustments
MIN_COMPLETION_TOKENS = int(os.getenv("MIN_COMPLETION_TOKENS", "128"))
# Upper cap for retries and overrides to avoid runaway costs
MAX_COMPLETION_TOKENS_CAP = int(os.getenv("MAX_COMPLETION_TOKENS_CAP", "2048"))

# LLM reasoning and verbosity configuration
def _validate_llm_config():
    """Validate and return LLM configuration values with defaults."""
    # Reasoning effort level: "minimal", "low", "medium", "high"
    reasoning_effort = os.getenv("LLM_REASONING_EFFORT", "medium").lower().strip()
    if reasoning_effort not in ("minimal", "low", "medium", "high"):
        logger.warning(f"Invalid LLM_REASONING_EFFORT '{reasoning_effort}', defaulting to 'medium'")
        reasoning_effort = "medium"
    
    # Verbosity level: "low", "medium", "high"
    verbosity = os.getenv("LLM_VERBOSITY", "low").lower().strip()
    if verbosity not in ("low", "medium", "high"):
        logger.warning(f"Invalid LLM_VERBOSITY '{verbosity}', defaulting to 'low'")
        verbosity = "low"
    
    return reasoning_effort, verbosity

LLM_REASONING_EFFORT, LLM_VERBOSITY = _validate_llm_config()

# ACR webhook configuration
ACR_WEBHOOK_TOKEN = os.getenv("ACR_WEBHOOK_TOKEN")
K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "respondr")
K8S_DEPLOYMENT = os.getenv("K8S_DEPLOYMENT", "respondr-deployment")

# Hostname redirect configuration
PRIMARY_HOSTNAME = os.getenv("PRIMARY_HOSTNAME", "respondr.scvsar.app")
_raw_legacy_hostnames = os.getenv("LEGACY_HOSTNAMES", "").split(",")
LEGACY_HOSTNAMES = [h.strip() for h in _raw_legacy_hostnames if h.strip()]

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
