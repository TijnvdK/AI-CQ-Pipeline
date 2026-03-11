from logging import getLogger

from boto3 import client as boto3_client

s3 = boto3_client("s3")
ssm = boto3_client("ssm")

logger = getLogger(__name__)

HTML_URLS_EXPIRE_IN = 3600  # 1 hour

def get_s3_bucket_name():
    try:
        response = ssm.get_parameter(Name="/ai-cq-pipeline/s3-bucket-name", WithDecryption=False)
        return response["Parameter"]["Value"]
    except Exception as e:
        logger.error(f"Error retrieving S3 bucket name: {e}")
        raise
def save_html_file_to_s3(key: str, body: str, content_type: str) -> str:
    bucket_name = get_s3_bucket_name()

    try:
        s3.put_object(Bucket=bucket_name, Key=key, Body=body, ContentType=content_type)
        logger.info(f"Successfully saved file to S3 at {key}.")

        private_url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": bucket_name, "Key": key},
            ExpiresIn=HTML_URLS_EXPIRE_IN,
        )

        return private_url
    except Exception as e:
        logger.error(f"Error saving file to S3 at {key}: {e}")
        raise
