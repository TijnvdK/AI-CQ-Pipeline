from logging import INFO, getLogger
from typing import Any, Dict

logger = getLogger(__name__)
logger.setLevel(INFO)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    logger.info(f"Received event: {event}")
    logger.info(f"Received context: {context}")
    return {"statusCode": 204, "body": ""}
