from json import dumps as json_dumps
from logging import INFO, getLogger
from os import environ

from boto3 import client as boto3_client

sf = boto3_client("stepfunctions")

logger = getLogger(__name__)
logger.setLevel(INFO)

if __name__ == "__main__":
    task_token = environ.get("TASK_TOKEN")
    if not task_token:
        logger.error("TASK_TOKEN environment variable not set")
        raise ValueError("TASK_TOKEN is required")

    sf.send_task_success(taskToken=task_token, output=json_dumps({"runLLM": False}))
