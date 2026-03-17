import pytest
from unittest.mock import Mock, patch

# 先 mock boto3.client，再导入模块，避免 import 时真实初始化 AWS client
with patch("boto3.client") as mock_boto3_client:
    mock_ssm = Mock()
    mock_boto3_client.return_value = mock_ssm

    import src.github_handler as github_handler


class TestGetGithubToken:
    def test_get_github_token_success(self):
        with patch.object(github_handler, "ssm") as mock_ssm:
            mock_ssm.get_parameter.return_value = {
                "Parameter": {
                    "Value": "fake-github-token"
                }
            }

            result = github_handler.get_github_token()

            assert result == "fake-github-token"
            mock_ssm.get_parameter.assert_called_once_with(
                Name="/ai-cq-pipeline/github-token",
                WithDecryption=True,
            )

    def test_get_github_token_failure_logs_and_raises(self):
        with patch.object(github_handler, "ssm") as mock_ssm, \
             patch.object(github_handler, "logger") as mock_logger:

            mock_ssm.get_parameter.side_effect = Exception("ssm error")

            with pytest.raises(Exception, match="ssm error"):
                github_handler.get_github_token()

            mock_logger.error.assert_called_once()
            assert "Error retrieving GitHub token" in mock_logger.error.call_args[0][0]


class TestGetGithubClient:
    def test_get_github_client_success(self):
        mock_auth_token = Mock(name="mock_auth_token")
        mock_github_instance = Mock(name="mock_github_instance")

        with patch.object(github_handler, "get_github_token", return_value="fake-token") as mock_get_token, \
             patch.object(github_handler.Auth, "Token", return_value=mock_auth_token) as mock_token_class, \
             patch.object(github_handler, "Github", return_value=mock_github_instance) as mock_github_class:

            result = github_handler.get_github_client()

            assert result == mock_github_instance
            mock_get_token.assert_called_once_with()
            mock_token_class.assert_called_once_with("fake-token")
            mock_github_class.assert_called_once_with(auth=mock_auth_token)


class TestPostCommentToPr:
    def setup_method(self):
        github_handler._github_client = None

    def test_post_comment_to_pr_success_with_new_client(self):
        mock_pr = Mock()
        mock_repo = Mock()
        mock_repo.get_pull.return_value = mock_pr

        mock_gh = Mock()
        mock_gh.get_repo.return_value = mock_repo

        with patch.object(github_handler, "get_github_client", return_value=mock_gh) as mock_get_client, \
             patch.object(github_handler, "logger") as mock_logger:

            github_handler.post_comment_to_pr(
                repo_name="owner/repo",
                pr_number=123,
                comment_body="hello world",
            )

            mock_get_client.assert_called_once_with()
            mock_gh.get_repo.assert_called_once_with("owner/repo")
            mock_repo.get_pull.assert_called_once_with(123)
            mock_pr.create_issue_comment.assert_called_once_with("hello world")
            mock_logger.info.assert_called_once_with(
                "Successfully posted comment to PR#123 in owner/repo."
            )

    def test_post_comment_to_pr_success_with_cached_client(self):
        mock_pr = Mock()
        mock_repo = Mock()
        mock_repo.get_pull.return_value = mock_pr

        mock_gh = Mock()
        mock_gh.get_repo.return_value = mock_repo

        github_handler._github_client = mock_gh

        with patch.object(github_handler, "get_github_client") as mock_get_client, \
             patch.object(github_handler, "logger") as mock_logger:

            github_handler.post_comment_to_pr(
                repo_name="owner/repo",
                pr_number=456,
                comment_body="cached client comment",
            )

            mock_get_client.assert_not_called()
            mock_gh.get_repo.assert_called_once_with("owner/repo")
            mock_repo.get_pull.assert_called_once_with(456)
            mock_pr.create_issue_comment.assert_called_once_with("cached client comment")
            mock_logger.info.assert_called_once_with(
                "Successfully posted comment to PR#456 in owner/repo."
            )

    def test_post_comment_to_pr_failure_logs_and_raises(self):
        mock_gh = Mock()
        mock_gh.get_repo.side_effect = Exception("github error")

        with patch.object(github_handler, "get_github_client", return_value=mock_gh), \
             patch.object(github_handler, "logger") as mock_logger:

            github_handler._github_client = None

            with pytest.raises(Exception, match="github error"):
                github_handler.post_comment_to_pr(
                    repo_name="owner/repo",
                    pr_number=789,
                    comment_body="will fail",
                )

            mock_logger.error.assert_called_once()
            assert "Error posting comment to PR#789 in owner/repo" in mock_logger.error.call_args[0][0]


class TestGetPrChangedFiles:
    def setup_method(self):
        github_handler._github_client = None

    def test_get_pr_changed_files_returns_only_python_files_with_new_client(self):
        mock_file_1 = Mock(filename="app/main.py")
        mock_file_2 = Mock(filename="README.md")
        mock_file_3 = Mock(filename="tests/test_main.py")
        mock_file_4 = Mock(filename="frontend/index.js")

        mock_pr = Mock()
        mock_pr.get_files.return_value = [mock_file_1, mock_file_2, mock_file_3, mock_file_4]

        mock_repo = Mock()
        mock_repo.get_pull.return_value = mock_pr

        mock_gh = Mock()
        mock_gh.get_repo.return_value = mock_repo

        with patch.object(github_handler, "get_github_client", return_value=mock_gh) as mock_get_client:
            result = github_handler.get_pr_changed_files("owner/repo", 321)

            assert result == ["app/main.py", "tests/test_main.py"]
            mock_get_client.assert_called_once_with()
            mock_gh.get_repo.assert_called_once_with("owner/repo")
            mock_repo.get_pull.assert_called_once_with(321)
            mock_pr.get_files.assert_called_once_with()

    def test_get_pr_changed_files_returns_only_python_files_with_cached_client(self):
        mock_file_1 = Mock(filename="module/a.py")
        mock_file_2 = Mock(filename="docs/guide.txt")

        mock_pr = Mock()
        mock_pr.get_files.return_value = [mock_file_1, mock_file_2]

        mock_repo = Mock()
        mock_repo.get_pull.return_value = mock_pr

        mock_gh = Mock()
        mock_gh.get_repo.return_value = mock_repo

        github_handler._github_client = mock_gh

        with patch.object(github_handler, "get_github_client") as mock_get_client:
            result = github_handler.get_pr_changed_files("owner/repo", 654)

            assert result == ["module/a.py"]
            mock_get_client.assert_not_called()
            mock_gh.get_repo.assert_called_once_with("owner/repo")
            mock_repo.get_pull.assert_called_once_with(654)
            mock_pr.get_files.assert_called_once_with()

    def test_get_pr_changed_files_returns_empty_list_when_no_python_files(self):
        mock_file_1 = Mock(filename="README.md")
        mock_file_2 = Mock(filename="frontend/app.js")

        mock_pr = Mock()
        mock_pr.get_files.return_value = [mock_file_1, mock_file_2]

        mock_repo = Mock()
        mock_repo.get_pull.return_value = mock_pr

        mock_gh = Mock()
        mock_gh.get_repo.return_value = mock_repo

        with patch.object(github_handler, "get_github_client", return_value=mock_gh):
            github_handler._github_client = None

            result = github_handler.get_pr_changed_files("owner/repo", 999)

            assert result == []
