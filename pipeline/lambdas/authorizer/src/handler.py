from hmac import compare_digest
from hmac import new as hmac_new
from logging import INFO, getLogger
from typing import Any, Dict

from boto3 import client as boto3_client
from botocore.exceptions import ClientError

ssm = boto3_client("ssm")

logger = getLogger(__name__)
logger.setLevel(INFO)


def get_github_webhook_secret():
    try:
        parameter = ssm.get_parameter(
            Name="/ai-cq-pipeline/github-webhook-secret", WithDecryption=True  # gitleaks:allow
        )
        return parameter["Parameter"]["Value"]
    except ClientError as e:
        logger.error(f"Error retrieving GitHub webhook secret: {e}")
        raise e


def generatePolicy(principalId, is_authorized, methodArn):
    return {
        "principalId": principalId,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": "Allow" if is_authorized else "Deny",
                    "Resource": methodArn,
                }
            ],
        },
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    try:
        signature_header = event["headers"].get("X-Hub-Signature-256", "")
        if not signature_header:
            return generatePolicy("user", False, event["methodArn"])

        secret = get_github_webhook_secret()
        payload = event["body"].encode("utf-8")
        expected_signature = (
            "sha256="
            + hmac_new(secret.encode("utf-8"), payload, digestmod="sha256").hexdigest()
        )

        if not compare_digest(signature_header, expected_signature):
            return generatePolicy("user", False, event["methodArn"])

        return generatePolicy("user", True, event["methodArn"])
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return generatePolicy("user", False, event["methodArn"])
