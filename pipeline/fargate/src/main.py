from logging import INFO
from logging import basicConfig as logging_basicConfig
from logging import getLogger
from os import environ
from tempfile import TemporaryDirectory

from git import Repo
from github_handler import (get_github_token, get_pr_changed_files,
                            post_comment_to_pr)
from llm_handler import refactor_issues_with_llm
from report_generator import create_report
from results_handler import apply_llm_changes, get_before_vs_after_metrics
from static_analysis import analyze_files

logging_basicConfig(
    level=INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

logger = getLogger(__name__)

def main() -> int:
    git_branch = environ.get("BRANCH", "")
    pr_number = environ.get("PR_NUMBER", "")
    repo_name = environ.get("REPO_NAME", "")

    if not git_branch or not pr_number or not repo_name:
        post_comment_to_pr(repo_name, int(pr_number), "An error occurred during pipeline execution. Please check the logs for details.")
        logger.error("Missing required environment variables: BRANCH, PR_NUMBER, REPO_NAME")
        return 1

    logger.info(f"Starting pipeline for PR#{pr_number} on branch {git_branch}.")
    post_comment_to_pr(repo_name, int(pr_number), f"Request received successfully. Starting analysis and refactoring for PR#{pr_number}...")

    try:
        with TemporaryDirectory() as code_dir:
            repo_url = f"https://{get_github_token()}@github.com/{repo_name}.git"
            repository = Repo.clone_from(repo_url, code_dir, branch=git_branch)
            logger.info(f"Successfully cloned repository from {repo_name} to {code_dir}.")

            changed_files = get_pr_changed_files(repo_name, int(pr_number))
            logger.info(f"Retrieved changed {len(changed_files)} files for PR#{pr_number}")

            sa_results = analyze_files(code_dir, changed_files)
            logger.info(f"Static analysis completed with {len(sa_results)} results.")

            llm_results = refactor_issues_with_llm(sa_results)
            logger.info(f"LLM refactoring completed with {len(llm_results)} results.")

            before_after_metrics = get_before_vs_after_metrics(sa_results, llm_results)
            report_url = create_report(pr_number, before_after_metrics)

            post_comment_to_pr(
                repo_name,
                int(pr_number),
                f"Analysis and refactoring completed for PR#{pr_number}. "
                f"Report generated with {len(llm_results)} issues.\n\n"
                f"Report URL (valid for seven days): [Open report]({report_url})"
            )

            applied = apply_llm_changes(llm_results)
            if applied > 0:
                refactor_branch_name = f"autofix/pr-{pr_number}"

                if refactor_branch_name in repository.branches:
                    repository.git.branch("-D", refactor_branch_name)
                    logger.info(f"Deleted existing branch {refactor_branch_name}.")

                repository.git.checkout("-b", refactor_branch_name)
                repository.git.add("--all")
                repository.git.commit("-m", f"Apply LLM-generated refactorings for PR#{pr_number}")
                repository.git.push("origin", refactor_branch_name, force=True)
                logger.info(f"Pushed refactor branch {refactor_branch_name} with applied changes.")
                post_comment_to_pr(repo_name, int(pr_number),
                    f"Applied {applied} LLM-generated refactorings to the codebase. "
                    f"A new branch `{refactor_branch_name}` has been created with these changes. "
                    "Tests will be run on that branch. You can review the changes in that branch "
                    "and merge it if you find the refactorings appropriate."
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
