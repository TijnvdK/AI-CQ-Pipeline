from logging import INFO, getLogger
from typing import Any, Dict

logger = getLogger(__name__)
logger.setLevel(INFO)

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    try:
        logger.info(f"Received event: {event}")
        logger.info(f"Received context: {context}")
        return {
            'status': 'completed',
            'batch_id': 1
        }
    except Exception as e:
        logger.error(f"Error processing event: {e}")
        return {
            'status': 'error',
            'error': str(e)
        }
