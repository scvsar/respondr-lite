"""
Scheduled task for purging old messages based on retention policy.
"""

import asyncio
import logging
from datetime import datetime
from .storage import purge_old_messages
from .config import RETENTION_DAYS, APP_TZ

logger = logging.getLogger(__name__)

# Run retention cleanup once per day (24 hours)
CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60


async def retention_cleanup_task():
    """Background task that periodically purges old messages."""
    
    if RETENTION_DAYS <= 0:
        logger.info("Message retention is disabled (RETENTION_DAYS <= 0), not starting cleanup task")
        return
    
    logger.info(f"Starting retention cleanup task (RETENTION_DAYS={RETENTION_DAYS}, interval={CLEANUP_INTERVAL_SECONDS}s)")
    
    while True:
        try:
            # Wait for the interval first (so we don't run immediately on startup)
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            
            # Run the purge
            logger.info(f"Running scheduled retention cleanup at {datetime.now(APP_TZ).isoformat()}")
            result = purge_old_messages()
            
            if result["active"] > 0 or result["deleted"] > 0:
                logger.info(f"Retention cleanup completed: purged {result['active']} active and {result['deleted']} deleted messages")
            else:
                logger.debug("Retention cleanup completed: no messages to purge")
                
        except Exception as e:
            logger.error(f"Error during retention cleanup: {e}", exc_info=True)
            # Continue running even if there's an error
            await asyncio.sleep(60)  # Short delay before retrying


async def run_retention_cleanup_now():
    """
    Run retention cleanup immediately (for manual trigger or testing).
    
    Returns:
        Dict with counts of purged active and deleted messages
    """
    logger.info(f"Running manual retention cleanup at {datetime.now(APP_TZ).isoformat()}")
    try:
        result = purge_old_messages()
        logger.info(f"Manual retention cleanup completed: purged {result['active']} active and {result['deleted']} deleted messages")
        return result
    except Exception as e:
        logger.error(f"Error during manual retention cleanup: {e}", exc_info=True)
        raise