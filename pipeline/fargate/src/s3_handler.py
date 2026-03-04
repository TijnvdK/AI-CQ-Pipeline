from logging import INFO, getLogger
from os import makedirs
from os.path import dirname
from os.path import join as path_join

from boto3 import client as boto3_client

s3 = boto3_client("s3")
ssm = boto3_client("ssm")

logger = getLogger(__name__)

def get_s3_bucket_name():
    try:
        response = ssm.get_parameter(Name="/ai-cq-pipeline/s3-bucket-name", WithDecryption=False)
        return response["Parameter"]["Value"]
    except Exception as e:
        logger.error(f"Error retrieving S3 bucket name: {e}")
        raise

def download_files_from_s3(s3_prefix: str, local_dir: str) -> bool:
    """
    Downloads all .py files from the specified S3 prefix to the local directory,
    preserving the directory structure.

    Raises:
        Exception: If there is an error during the S3 download process.

    Args:
        s3_prefix (str): The S3 prefix to download files from.
        local_dir (str): The local directory to download files to.

    Returns:
        bool: True if any files were downloaded, False otherwise.
    """

    files_downloaded = False

    bucket_name = get_s3_bucket_name()

    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket_name, Prefix=s3_prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]

                relative_path = key[len(s3_prefix):].lstrip("/")
                if not relative_path or not relative_path.endswith(".py"):
                    continue

                local_path = path_join(local_dir, relative_path)
                makedirs(dirname(local_path), exist_ok=True)

                s3.download_file(bucket_name, key, local_path)

                if not files_downloaded:
                    files_downloaded = True

        return files_downloaded
    except Exception as e:
        logger.error(f"Error downloading files from S3: {e}")
        raise
