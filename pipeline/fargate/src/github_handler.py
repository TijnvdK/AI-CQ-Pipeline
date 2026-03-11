from logging import getLogger
from typing import List
from boto3 import client as boto3_client
from github import Auth
from github import Github

ssm = boto3_client("ssm")

logger = getLogger(__name__)

# Save global copy of GitHub client to prevent multiple instantiations
_github_client = None

def get_github_token() -> str:
    try:
        response = ssm.get_parameter(Name="/ai-cq-pipeline/github-token", WithDecryption=True)
        return response["Parameter"]["Value"]
    except Exception as e:
        logger.error(f"Error retrieving GitHub token: {e}")
        raise


def get_github_client() -> Github:
    token = get_github_token()
    auth = Auth.Token(token)
    return Github(auth=auth)

def post_comment_to_pr(repo_name: str, pr_number: int, comment_body: str) -> None:
    global _github_client
    try:
        if _github_client is None:
            _github_client = get_github_client()

        gh = _github_client
        repo = gh.get_repo(repo_name)
        pr = repo.get_pull(pr_number)
        pr.create_issue_comment(comment_body)
        logger.info(f"Successfully posted comment to PR#{pr_number} in {repo_name}.")
    except Exception as e:
        logger.error(f"Error posting comment to PR#{pr_number} in {repo_name}: {e}")
        raise

def get_pr_changed_files(repo_name: str, pr_number: int) -> List[str]:
    global _github_client
    if _github_client is None:
            _github_client = get_github_client()

    gh = _github_client
    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pr_number)

    return [f.filename for f in pr.get_files() if f.filename.endswith(".py")]

