from logging import INFO
from logging import basicConfig as logging_basicConfig
from logging import getLogger
from os import environ
from tempfile import TemporaryDirectory

from llm_handler import refactor_issues_with_llm
from report_generator import create_report
from s3_handler import download_files_from_s3
from results_handler import get_before_vs_after_metrics
from static_analysis import analyze_dir
from github_handler import post_comment_to_pr

logging_basicConfig(
    level=INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

logger = getLogger(__name__)

def main() -> int:
    git_branch = environ.get("BRANCH", "")
    pr_number = environ.get("PR_NUMBER", "")
    repo_name = environ.get("REPO_NAME", "")
    s3_prefix = environ.get("S3_PREFIX", "")

    if not git_branch or not pr_number or not repo_name or not s3_prefix:
        post_comment_to_pr(repo_name, int(pr_number), "An error occurred during pipeline execution. Please check the logs for details.")
        logger.error("Missing required environment variables: BRANCH, PR_NUMBER, REPO_NAME, S3_PREFIX")
        return 1

    logger.info(f"Starting pipeline for PR#{pr_number} on branch {git_branch}.")
    post_comment_to_pr(repo_name, int(pr_number), f"Request received successfully. Starting analysis and refactoring for PR#{pr_number}...")

    try:
        with TemporaryDirectory() as code_dir:
            any_downloaded_files = download_files_from_s3(s3_prefix, code_dir)

            if not any_downloaded_files:
                logger.info(f"No .py files found in S3 prefix {s3_prefix}. Exiting.")
                return 0

            logger.info(f"Successfully downloaded files from S3 prefix {s3_prefix} to {code_dir}.")

            sa_results = analyze_dir(code_dir)
            logger.info(f"Static analysis completed with {len(sa_results)} results.")

            llm_results = refactor_issues_with_llm(sa_results)
            logger.info(f"LLM refactoring completed with {len(llm_results)} results.")

            before_after_metrics = get_before_vs_after_metrics(sa_results, llm_results)
            report_url = create_report(pr_number, before_after_metrics)

            post_comment_to_pr(repo_name, int(pr_number),
                f"Analysis and refactoring completed for PR#{pr_number}. "
                f"Report generated with {len(llm_results)} issues. "
                f"Please check the report for details, which can be accessed here: {report_url}. "
                "The URL is valid for one hour."
            )

            return 0
    except Exception as e:
        post_comment_to_pr(repo_name, int(pr_number), "An error occurred during pipeline execution. Please check the logs for details.")
        logger.error(f"An error occurred during pipeline execution: {e}")
        return 1

if __name__ == "__main__":
    if (main() == 0):
        logger.info("Pipeline completed successfully.")
    else:
        logger.error("Pipeline failed with errors.")
