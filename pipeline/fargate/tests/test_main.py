import importlib
import sys
import types
from unittest.mock import Mock, patch

import pytest

# 先伪造 main.py 依赖的模块，避免 import src.main 时失败
fake_llm_handler = types.ModuleType("llm_handler")
fake_llm_handler.refactor_issues_with_llm = Mock()

fake_report_generator = types.ModuleType("report_generator")
fake_report_generator.create_report = Mock()

fake_results_handler = types.ModuleType("results_handler")
fake_results_handler.apply_llm_changes = Mock()
fake_results_handler.get_before_vs_after_metrics = Mock()

fake_static_analysis = types.ModuleType("static_analysis")
fake_static_analysis.analyze_files = Mock()

fake_github_handler = types.ModuleType("github_handler")
fake_github_handler.get_pr_changed_files = Mock()
fake_github_handler.post_comment_to_pr = Mock()
fake_github_handler.get_github_token = Mock()

fake_git = types.ModuleType("git")
fake_git.Repo = Mock()

sys.modules["llm_handler"] = fake_llm_handler
sys.modules["report_generator"] = fake_report_generator
sys.modules["results_handler"] = fake_results_handler
sys.modules["static_analysis"] = fake_static_analysis
sys.modules["github_handler"] = fake_github_handler
sys.modules["git"] = fake_git

import src.main as main_module


class TestMain:
    def test_main_returns_1_when_required_env_missing(self):
        with patch.dict(
            main_module.environ,
            {"BRANCH": "", "PR_NUMBER": "123", "REPO_NAME": "owner/repo"},
            clear=True,
        ), patch.object(main_module, "post_comment_to_pr") as mock_post_comment, \
             patch.object(main_module, "logger") as mock_logger:

            result = main_module.main()

            assert result == 1
            mock_post_comment.assert_called_once_with(
                "owner/repo",
                123,
                "An error occurred during pipeline execution. Please check the logs for details.",
            )
            mock_logger.error.assert_called_once_with(
                "Missing required environment variables: BRANCH, PR_NUMBER, REPO_NAME"
            )

    def test_main_success_without_applied_changes(self):
        mock_repository = Mock()
        mock_repository.branches = []

        with patch.dict(
            main_module.environ,
            {"BRANCH": "feature/test", "PR_NUMBER": "123", "REPO_NAME": "owner/repo"},
            clear=True,
        ), patch.object(main_module, "TemporaryDirectory") as mock_temp_dir, \
             patch.object(main_module, "get_github_token", return_value="fake-token"), \
             patch.object(main_module.Repo, "clone_from", return_value=mock_repository) as mock_clone_from, \
             patch.object(main_module, "get_pr_changed_files", return_value=["a.py", "b.py"]) as mock_get_changed_files, \
             patch.object(main_module, "analyze_files", return_value=[{"id": "issue1"}]) as mock_analyze_files, \
             patch.object(main_module, "refactor_issues_with_llm", return_value=[{"after_code": "x"}]) as mock_refactor, \
             patch.object(main_module, "get_before_vs_after_metrics", return_value=[{"metric": 1}]) as mock_metrics, \
             patch.object(main_module, "create_report", return_value="https://report-url") as mock_create_report, \
             patch.object(main_module, "apply_llm_changes", return_value=0) as mock_apply_changes, \
             patch.object(main_module, "post_comment_to_pr") as mock_post_comment:

            mock_temp_dir.return_value.__enter__.return_value = "/tmp/code-dir"
            mock_temp_dir.return_value.__exit__.return_value = None

            result = main_module.main()

            assert result == 0

            mock_clone_from.assert_called_once_with(
                "https://fake-token@github.com/owner/repo.git",
                "/tmp/code-dir",
                branch="feature/test",
            )
            mock_get_changed_files.assert_called_once_with("owner/repo", 123)
            mock_analyze_files.assert_called_once_with("/tmp/code-dir", ["a.py", "b.py"])
            mock_refactor.assert_called_once_with([{"id": "issue1"}])
            mock_metrics.assert_called_once_with([{"id": "issue1"}], [{"after_code": "x"}])
            mock_create_report.assert_called_once_with("123", [{"metric": 1}])
            mock_apply_changes.assert_called_once_with([{"after_code": "x"}])

            assert mock_post_comment.call_count == 2
            mock_post_comment.assert_any_call(
                "owner/repo",
                123,
                "Request received successfully. Starting analysis and refactoring for PR#123...",
            )
            mock_post_comment.assert_any_call(
                "owner/repo",
                123,
                "Analysis and refactoring completed for PR#123. "
                "Report generated with 1 issues.\n\n"
                "Report URL (valid for seven days): [Open report](https://report-url)"
            )

            mock_repository.git.checkout.assert_not_called()
            mock_repository.git.add.assert_not_called()
            mock_repository.git.commit.assert_not_called()
            mock_repository.git.push.assert_not_called()

    def test_main_success_with_applied_changes_pushes_branch(self):
        mock_repository = Mock()
        mock_repository.branches = []

        with patch.dict(
            main_module.environ,
            {"BRANCH": "feature/test", "PR_NUMBER": "456", "REPO_NAME": "owner/repo"},
            clear=True,
        ), patch.object(main_module, "TemporaryDirectory") as mock_temp_dir, \
             patch.object(main_module, "get_github_token", return_value="fake-token"), \
             patch.object(main_module.Repo, "clone_from", return_value=mock_repository), \
             patch.object(main_module, "get_pr_changed_files", return_value=["a.py"]), \
             patch.object(main_module, "analyze_files", return_value=[{"id": "issue1"}]), \
             patch.object(main_module, "refactor_issues_with_llm", return_value=[{"after_code": "new"}]), \
             patch.object(main_module, "get_before_vs_after_metrics", return_value=[{"metric": 1}]), \
             patch.object(main_module, "create_report", return_value="https://report-url"), \
             patch.object(main_module, "apply_llm_changes", return_value=2), \
             patch.object(main_module, "post_comment_to_pr") as mock_post_comment:

            mock_temp_dir.return_value.__enter__.return_value = "/tmp/code-dir"
            mock_temp_dir.return_value.__exit__.return_value = None

            result = main_module.main()

            assert result == 0

            mock_repository.git.checkout.assert_called_once_with("-b", "autofix/pr-456")
            mock_repository.git.add.assert_called_once_with("--all")
            mock_repository.git.commit.assert_called_once_with(
                "-m",
                "Apply LLM-generated refactorings for PR#456",
            )
            mock_repository.git.push.assert_called_once_with(
                "origin",
                "autofix/pr-456",
                force=True,
            )

            assert mock_post_comment.call_count == 3
            mock_post_comment.assert_any_call(
                "owner/repo",
                456,
                "Applied 2 LLM-generated refactorings to the codebase. "
                "A new branch `autofix/pr-456` has been created with these changes. "
                "Tests will be run on that branch. You can review the changes in that branch "
                "and merge it if you find the refactorings appropriate."
            )

    def test_main_deletes_existing_refactor_branch_before_recreating(self):
        mock_repository = Mock()
        mock_repository.branches = ["autofix/pr-789"]

        with patch.dict(
            main_module.environ,
            {"BRANCH": "feature/test", "PR_NUMBER": "789", "REPO_NAME": "owner/repo"},
            clear=True,
        ), patch.object(main_module, "TemporaryDirectory") as mock_temp_dir, \
             patch.object(main_module, "get_github_token", return_value="fake-token"), \
             patch.object(main_module.Repo, "clone_from", return_value=mock_repository), \
             patch.object(main_module, "get_pr_changed_files", return_value=["a.py"]), \
             patch.object(main_module, "analyze_files", return_value=[{"id": "issue1"}]), \
             patch.object(main_module, "refactor_issues_with_llm", return_value=[{"after_code": "new"}]), \
             patch.object(main_module, "get_before_vs_after_metrics", return_value=[{"metric": 1}]), \
             patch.object(main_module, "create_report", return_value="https://report-url"), \
             patch.object(main_module, "apply_llm_changes", return_value=1), \
             patch.object(main_module, "post_comment_to_pr"):

            mock_temp_dir.return_value.__enter__.return_value = "/tmp/code-dir"
            mock_temp_dir.return_value.__exit__.return_value = None

            result = main_module.main()

            assert result == 0
            mock_repository.git.branch.assert_called_once_with("-D", "autofix/pr-789")
            mock_repository.git.checkout.assert_called_once_with("-b", "autofix/pr-789")

    def test_main_returns_1_and_comments_when_exception_happens(self):
        with patch.dict(
            main_module.environ,
            {"BRANCH": "feature/test", "PR_NUMBER": "123", "REPO_NAME": "owner/repo"},
            clear=True,
        ), patch.object(main_module, "post_comment_to_pr") as mock_post_comment, \
             patch.object(main_module, "TemporaryDirectory") as mock_temp_dir, \
             patch.object(main_module, "get_github_token", side_effect=Exception("boom")), \
             patch.object(main_module, "logger") as mock_logger:

            mock_temp_dir.return_value.__enter__.return_value = "/tmp/code-dir"
            mock_temp_dir.return_value.__exit__.return_value = None

            result = main_module.main()

            assert result == 1

            assert mock_post_comment.call_count == 2
            mock_post_comment.assert_any_call(
                "owner/repo",
                123,
                "Request received successfully. Starting analysis and refactoring for PR#123...",
            )
            mock_post_comment.assert_any_call(
                "owner/repo",
                123,
                "An error occurred during pipeline execution. Please check the logs for details.",
            )

            mock_logger.error.assert_called_once()
            assert "An error occurred during pipeline execution: boom" in mock_logger.error.call_args[0][0]
