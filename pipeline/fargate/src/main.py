from logging import INFO
from logging import basicConfig as logging_basicConfig
from logging import getLogger
from os import environ
from tempfile import TemporaryDirectory

from s3_handler import download_files_from_s3

logging_basicConfig(
    level=INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

logger = getLogger(__name__)

def main():
    git_branch = environ.get("BRANCH", "")
    pr_number = environ.get("PR_NUMBER", "")
    s3_prefix = environ.get("S3_PREFIX", "")

    if not git_branch or not pr_number or not s3_prefix:
        logger.error("Missing required environment variables: BRANCH, PR_NUMBER, S3_PREFIX")
        exit(1)

    logger.info(f"Starting pipeline for PR#{pr_number} on branch {git_branch}.")

    with TemporaryDirectory() as code_dir:
        any_downloaded_files = download_files_from_s3(s3_prefix, code_dir)

        if not any_downloaded_files:
            logger.info(f"No .py files found in S3 prefix {s3_prefix}. Exiting.")
            return

        logger.info(f"Successfully downloaded files from S3 prefix {s3_prefix} to {code_dir}.")

if __name__ == "__main__":
    main()
