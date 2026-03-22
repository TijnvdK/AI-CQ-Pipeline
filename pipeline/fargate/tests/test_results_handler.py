import sys
import types
from unittest.mock import Mock, patch

import pytest

# 先伪造依赖模块，避免 import src.results_handler 失败
fake_llm_handler = types.ModuleType("llm_handler")
fake_llm_handler.RefactoredResponse = dict

fake_static_analysis = types.ModuleType("static_analysis")
fake_static_analysis.AnalysisResult = dict
fake_static_analysis.FunctionMetrics = dict
fake_static_analysis.SourceLocation = dict
fake_static_analysis.analyze_file = Mock()

sys.modules["llm_handler"] = fake_llm_handler
sys.modules["static_analysis"] = fake_static_analysis

import src.results_handler as results_handler


class TestGetBeforeVsAfterMetrics:
    def test_get_before_vs_after_metrics_with_after_code(self):
        sa_results = [
            {
                "source": {
                    "file": "a.py",
                    "start_line": 1,
                    "end_line": 3,
                },
                "metrics": {
                    "cc": 5,
                    "mi": 80,
                    "smells": [],
                },
            }
        ]

        llm_results = [
            {
                "source": {
                    "file": "a.py",
                    "start_line": 1,
                    "end_line": 3,
                },
                "before_code": "def foo():\n    pass\n",
                "after_code": "def foo():\n    return 1\n",
            }
        ]

        mock_tmp = Mock()
        mock_tmp.__enter__ = Mock(return_value=mock_tmp)
        mock_tmp.__exit__ = Mock(return_value=None)
        mock_tmp.name = "temp_after.py"

        after_analysis = [
            {"metrics": {"cc": 2, "mi": 95, "smells": []}},
            {"metrics": {"cc": 1, "mi": 99, "smells": []}},
        ]

        with patch.object(results_handler, "NamedTemporaryFile", return_value=mock_tmp), \
             patch.object(results_handler, "analyze_file", return_value=after_analysis) as mock_analyze, \
             patch.object(results_handler, "os_unlink") as mock_unlink, \
             patch.object(results_handler, "logger") as mock_logger:

            result = results_handler.get_before_vs_after_metrics(sa_results, llm_results)

            assert len(result) == 1
            assert result[0]["source"] == {
                "file": "a.py",
                "start_line": 1,
                "end_line": 3,
            }
            assert result[0]["before_code"] == "def foo():\n    pass\n"
            assert result[0]["after_code"] == "def foo():\n    return 1\n"
            assert result[0]["before_metrics"] == {"cc": 5, "mi": 80, "smells": []}
            assert result[0]["after_metrics"] == [
                {"cc": 2, "mi": 95, "smells": []},
                {"cc": 1, "mi": 99, "smells": []},
            ]

            mock_tmp.write.assert_called_once_with("def foo():\n    return 1\n")
            mock_analyze.assert_called_once_with("temp_after.py")
            mock_unlink.assert_called_once_with("temp_after.py")
            mock_logger.info.assert_called_once()

    def test_get_before_vs_after_metrics_without_after_code(self):
        sa_results = [
            {
                "source": {
                    "file": "a.py",
                    "start_line": 1,
                    "end_line": 3,
                },
                "metrics": {
                    "cc": 5,
                    "mi": 80,
                    "smells": [],
                },
            }
        ]

        llm_results = [
            {
                "source": {
                    "file": "a.py",
                    "start_line": 1,
                    "end_line": 3,
                },
                "before_code": "def foo():\n    pass\n",
                "after_code": None,
            }
        ]

        result = results_handler.get_before_vs_after_metrics(sa_results, llm_results)

        assert len(result) == 1
        assert result[0]["before_metrics"] == {"cc": 5, "mi": 80, "smells": []}
        assert result[0]["after_metrics"] is None

    def test_get_before_vs_after_metrics_skips_when_before_metrics_missing(self):
        sa_results = []
        llm_results = [
            {
                "source": {
                    "file": "missing.py",
                    "start_line": 10,
                    "end_line": 20,
                },
                "before_code": "def foo():\n    pass\n",
                "after_code": "def foo():\n    return 1\n",
            }
        ]

        with patch.object(results_handler, "logger") as mock_logger:
            result = results_handler.get_before_vs_after_metrics(sa_results, llm_results)

            assert result == []
            mock_logger.warning.assert_called_once()
            assert "No static analysis metrics found" in mock_logger.warning.call_args[0][0]

    def test_get_before_vs_after_metrics_unlinks_temp_file_even_when_analysis_fails(self):
        sa_results = [
            {
                "source": {
                    "file": "a.py",
                    "start_line": 1,
                    "end_line": 3,
                },
                "metrics": {
                    "cc": 5,
                    "mi": 80,
                    "smells": [],
                },
            }
        ]

        llm_results = [
            {
                "source": {
                    "file": "a.py",
                    "start_line": 1,
                    "end_line": 3,
                },
                "before_code": "def foo():\n    pass\n",
                "after_code": "def foo():\n    return 1\n",
            }
        ]

        mock_tmp = Mock()
        mock_tmp.__enter__ = Mock(return_value=mock_tmp)
        mock_tmp.__exit__ = Mock(return_value=None)
        mock_tmp.name = "temp_after.py"

        with patch.object(results_handler, "NamedTemporaryFile", return_value=mock_tmp), \
             patch.object(results_handler, "analyze_file", side_effect=Exception("analysis failed")), \
             patch.object(results_handler, "os_unlink") as mock_unlink:

            with pytest.raises(Exception, match="analysis failed"):
                results_handler.get_before_vs_after_metrics(sa_results, llm_results)

            mock_unlink.assert_called_once_with("temp_after.py")


class TestApplyLlmChanges:
    def test_apply_llm_changes_returns_0_when_no_after_code(self, tmp_path):
        file_path = tmp_path / "a.py"
        original = (
            "def foo():\n"
            "    return 1\n"
        )
        file_path.write_text(original, encoding="utf-8")

        llm_results = [
            {
                "source": {
                    "file": str(file_path),
                    "start_line": 1,
                    "end_line": 2,
                },
                "before_code": original,
                "after_code": None,
            }
        ]

        with patch.object(results_handler, "logger") as mock_logger:
            applied = results_handler.apply_llm_changes(llm_results)

            assert applied == 0
            assert file_path.read_text(encoding="utf-8") == original
            mock_logger.info.assert_called_once_with(
                "Applied 0 LLM-generated refactorings to codebase."
            )

    def test_apply_llm_changes_replaces_function_code(self, tmp_path):
        file_path = tmp_path / "sample.py"
        file_path.write_text(
            "def foo():\n"
            "    x = 1\n"
            "    return x\n"
            "\n"
            "def bar():\n"
            "    return 2\n",
            encoding="utf-8",
        )

        llm_results = [
            {
                "source": {
                    "file": str(file_path),
                    "start_line": 1,
                    "end_line": 3,
                },
                "before_code": "def foo():\n    x = 1\n    return x\n",
                "after_code": "def foo():\n    return 99\n",
            }
        ]

        applied = results_handler.apply_llm_changes(llm_results)

        assert applied == 1
        content = file_path.read_text(encoding="utf-8")
        assert "def foo():\n    return 99\n" in content
        assert "def bar():\n    return 2\n" in content

    def test_apply_llm_changes_reindents_nested_function_code(self, tmp_path):
        file_path = tmp_path / "nested.py"
        file_path.write_text(
            "class A:\n"
            "    def foo(self):\n"
            "        x = 1\n"
            "        return x\n",
            encoding="utf-8",
        )

        llm_results = [
            {
                "source": {
                    "file": str(file_path),
                    "start_line": 2,
                    "end_line": 4,
                },
                "before_code": "    def foo(self):\n        x = 1\n        return x\n",
                "after_code": "def foo(self):\n    return 123\n",
            }
        ]

        applied = results_handler.apply_llm_changes(llm_results)

        assert applied == 1
        content = file_path.read_text(encoding="utf-8")
        assert "class A:\n" in content
        assert "    def foo(self):\n" in content
        assert "        return 123\n" in content

    def test_apply_llm_changes_sorts_changes_in_reverse_line_order(self, tmp_path):
        file_path = tmp_path / "multi.py"
        file_path.write_text(
            "def first():\n"
            "    return 1\n"
            "\n"
            "def second():\n"
            "    return 2\n",
            encoding="utf-8",
        )

        llm_results = [
            {
                "source": {
                    "file": str(file_path),
                    "start_line": 1,
                    "end_line": 2,
                },
                "before_code": "def first():\n    return 1\n",
                "after_code": "def first():\n    return 10\n",
            },
            {
                "source": {
                    "file": str(file_path),
                    "start_line": 4,
                    "end_line": 5,
                },
                "before_code": "def second():\n    return 2\n",
                "after_code": "def second():\n    return 20\n",
            },
        ]

        applied = results_handler.apply_llm_changes(llm_results)

        assert applied == 2
        content = file_path.read_text(encoding="utf-8")
        assert "def first():\n    return 10\n" in content
        assert "def second():\n    return 20\n" in content

    def test_apply_llm_changes_ensures_trailing_newline_on_inserted_code(self, tmp_path):
        file_path = tmp_path / "newline.py"
        file_path.write_text(
            "def foo():\n"
            "    return 1\n",
            encoding="utf-8",
        )

        llm_results = [
            {
                "source": {
                    "file": str(file_path),
                    "start_line": 1,
                    "end_line": 2,
                },
                "before_code": "def foo():\n    return 1\n",
                "after_code": "def foo():\n    return 42",
            }
        ]

        applied = results_handler.apply_llm_changes(llm_results)

        assert applied == 1
        content = file_path.read_text(encoding="utf-8")
        assert content == "def foo():\n    return 42\n"

