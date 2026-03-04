from logging import INFO, getLogger
from typing import Any, Dict
import json
import boto3
from datetime import datetime, timezone

logger = getLogger(__name__)
logger.setLevel(INFO)

S3_BUCKET = "ai-cq-pipeline-s3-main"

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    logger.info(f"Received event: {event}")

    body = event.get("body", {})
    if isinstance(body, str):
        body = json.loads(body)

    entry = {
        "id": body.get("id"),
        "result": body.get("result"),
        "total": body.get("total"),
        "failed": body.get("failed"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    s3 = boto3.client("s3")
    key = f"test-reports/pr-{entry['id']}/report.jsonl"

    try:
        existing = s3.get_object(Bucket=S3_BUCKET, Key=key)
        lines = existing["Body"].read().decode("utf-8").strip().splitlines()
        entries = [json.loads(l) for l in lines if l]
    except s3.exceptions.NoSuchKey:
        entries = []

    entries.append(entry)
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body="\n".join(json.dumps(e) for e in entries).encode("utf-8"),
    )
    return {"statusCode": 204, "body": ""}
