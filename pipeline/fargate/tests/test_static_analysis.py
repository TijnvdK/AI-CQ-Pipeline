import ast
from unittest.mock import Mock, patch

import pytest

import src.static_analysis as static_analysis


SAMPLE_CODE = """
def simple_function(x):
    return x + 1

def moderate_function(x, y):
    if x > 0:
        if y > 0:
            return x + y
        else:
            return x - y
    return 0

async def async_function():
    return 42
"""


@pytest.fixture
def sample_file(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_CODE, encoding="utf-8")
    return str(f)


class TestLoadAst:
    def test_load_ast(self, sample_file):
        tree, source = static_analysis.load_ast(sample_file)

        assert isinstance(tree, ast.Module)
        assert "simple_function" in source
        assert "moderate_function" in source


class TestGetFunctions:
    def test_get_functions(self, sample_file):
        tree, source = static_analysis.load_ast(sample_file)
        functions = static_analysis.get_functions(tree, source)
        names = [f["name"] for f in functions]

        assert len(functions) == 3
        assert "simple_function" in names
        assert "moderate_function" in names
        assert "async_function" in names

    def test_get_functions_have_required_fields(self, sample_file):
        tree, source = static_analysis.load_ast(sample_file)
        functions = static_analysis.get_functions(tree, source)

        for func in functions:
            assert "name" in func
            assert "source" in func
            assert "start_line" in func
            assert "end_line" in func
            assert isinstance(func["name"], str)
            assert isinstance(func["source"], str)
            assert isinstance(func["start_line"], int)
            assert isinstance(func["end_line"], int)

    def test_get_functions_extracts_source_segment(self, sample_file):
        tree, source = static_analysis.load_ast(sample_file)
        functions = static_analysis.get_functions(tree, source)

        simple_fn = next(f for f in functions if f["name"] == "simple_function")
        moderate_fn = next(f for f in functions if f["name"] == "moderate_function")
        async_fn = next(f for f in functions if f["name"] == "async_function")

        assert "def simple_function(x):" in simple_fn["source"]
        assert "return x + 1" in simple_fn["source"]

        assert "def moderate_function(x, y):" in moderate_fn["source"]
        assert "return x - y" in moderate_fn["source"]

        assert "async def async_function():" in async_fn["source"]
        assert "return 42" in async_fn["source"]


class TestGetSmells:
    def test_get_smells_maps_messages_to_matching_functions(self):
        results = [
            {
                "id": "simple_function",
                "source": {"file": "sample.py", "start_line": 2, "end_line": 3},
                "metrics": {"cc": 1, "mi": 100.0, "smells": []},
            },
            {
                "id": "moderate_function",
                "source": {"file": "sample.py", "start_line": 5, "end_line": 11},
                "metrics": {"cc": 3, "mi": 80.0, "smells": []},
            },
        ]

        pylint_output = """
[
  {
    "type": "convention",
    "module": "sample",
    "obj": "simple_function",
    "line": 2,
    "column": 0,
    "endLine": 2,
    "endColumn": 19,
    "path": "sample.py",
    "symbol": "missing-function-docstring",
    "message": "Missing function or method docstring",
    "message-id": "C0116"
  },
  {
    "type": "warning",
    "module": "sample",
    "obj": "moderate_function",
    "line": 8,
    "column": 8,
    "endLine": 8,
    "endColumn": 20,
    "path": "sample.py",
    "symbol": "no-else-return",
    "message": "Unnecessary else after return",
    "message-id": "R1705"
  },
  {
    "type": "warning",
    "module": "sample",
    "obj": "outside",
    "line": 20,
    "column": 0,
    "endLine": 20,
    "endColumn": 1,
    "path": "sample.py",
    "symbol": "unused-variable",
    "message": "Unused variable 'z'",
    "message-id": "W0612"
  }
]
"""

        mock_completed = Mock()
        mock_completed.stdout = pylint_output

        with patch.object(static_analysis, "subprocess_run", return_value=mock_completed) as mock_run:
            updated = static_analysis.get_smells(results, "sample.py")

            mock_run.assert_called_once_with(
                ["pylint", "sample.py", "--output-format=json"],
                capture_output=True,
                text=True,
                timeout=60,
            )

        assert len(updated[0]["metrics"]["smells"]) == 1
        assert updated[0]["metrics"]["smells"][0]["line"] == 2
        assert updated[0]["metrics"]["smells"][0]["code"] == "C0116"
        assert updated[0]["metrics"]["smells"][0]["message"] == "Missing function or method docstring"
        assert updated[0]["metrics"]["smells"][0]["symbol"] == "missing-function-docstring"

        assert len(updated[1]["metrics"]["smells"]) == 1
        assert updated[1]["metrics"]["smells"][0]["line"] == 8
        assert updated[1]["metrics"]["smells"][0]["code"] == "R1705"
        assert updated[1]["metrics"]["smells"][0]["message"] == "Unnecessary else after return"
        assert updated[1]["metrics"]["smells"][0]["symbol"] == "no-else-return"

    def test_get_smells_returns_empty_smells_when_pylint_fails(self):
        results = [
            {
                "id": "simple_function",
                "source": {"file": "sample.py", "start_line": 1, "end_line": 2},
                "metrics": {"cc": 1, "mi": 100.0, "smells": []},
            }
        ]

        with patch.object(static_analysis, "subprocess_run", side_effect=Exception("pylint failed")), \
             patch.object(static_analysis, "logger") as mock_logger:

            updated = static_analysis.get_smells(results, "sample.py")

            assert updated[0]["metrics"]["smells"] == []
            mock_logger.error.assert_called_once()
            assert "Error running pylint on sample.py" in mock_logger.error.call_args[0][0]

    def test_get_smells_handles_empty_stdout(self):
        results = [
            {
                "id": "simple_function",
                "source": {"file": "sample.py", "start_line": 1, "end_line": 2},
                "metrics": {"cc": 1, "mi": 100.0, "smells": []},
            }
        ]

        mock_completed = Mock()
        mock_completed.stdout = ""

        with patch.object(static_analysis, "subprocess_run", return_value=mock_completed):
            updated = static_analysis.get_smells(results, "sample.py")

        assert updated[0]["metrics"]["smells"] == []


class TestAnalyzeFile:
    def test_analyze_file_returns_expected_structure(self, sample_file):
        with patch.object(static_analysis, "get_smells", side_effect=lambda results, _: results):
            results = static_analysis.analyze_file(sample_file)

        assert len(results) >= 2

        for result in results:
            assert "id" in result
            assert "source" in result
            assert "metrics" in result

            assert "file" in result["source"]
            assert "start_line" in result["source"]
            assert "end_line" in result["source"]

            assert "cc" in result["metrics"]
            assert "mi" in result["metrics"]
            assert "smells" in result["metrics"]

            assert result["source"]["file"] == sample_file
            assert isinstance(result["metrics"]["cc"], int)
            assert isinstance(result["metrics"]["mi"], float)
            assert isinstance(result["metrics"]["smells"], list)

    def test_analyze_file_calls_get_smells(self, sample_file):
        with patch.object(static_analysis, "get_smells", side_effect=lambda results, _: results) as mock_get_smells:
            results = static_analysis.analyze_file(sample_file)

            assert len(results) >= 1
            mock_get_smells.assert_called_once()
            args = mock_get_smells.call_args.args
            assert args[1] == sample_file

    def test_analyze_file_skips_functions_without_cc_results(self, sample_file):
        fake_functions = [
            {
                "name": "fn1",
                "source": "def fn1():\n    pass\n",
                "start_line": 1,
                "end_line": 2,
            },
            {
                "name": "fn2",
                "source": "def fn2():\n    return 1\n",
                "start_line": 4,
                "end_line": 5,
            },
        ]

        fake_tree = ast.parse("pass")
        fake_source = "pass"

        cc_item = Mock()
        cc_item.complexity = 2

        with patch.object(static_analysis, "load_ast", return_value=(fake_tree, fake_source)), \
             patch.object(static_analysis, "get_functions", return_value=fake_functions), \
             patch.object(static_analysis, "cc_visit", side_effect=[[cc_item], []]), \
             patch.object(static_analysis, "mi_visit", side_effect=[88.123, 77.456]), \
             patch.object(static_analysis, "get_smells", side_effect=lambda results, _: results):

            results = static_analysis.analyze_file(sample_file)

        assert len(results) == 1
        assert results[0]["id"] == "fn1"
        assert results[0]["metrics"]["cc"] == 2
        assert results[0]["metrics"]["mi"] == 88.12
        assert results[0]["metrics"]["smells"] == []


class TestAnalyzeFiles:
    def test_analyze_files_aggregates_results(self, tmp_path):
        base_dir = tmp_path
        file1 = base_dir / "a.py"
        file2 = base_dir / "b.py"

        file1.write_text("def a():\n    return 1\n", encoding="utf-8")
        file2.write_text("def b():\n    return 2\n", encoding="utf-8")

        analyze_results_1 = [
            {
                "id": "a",
                "source": {"file": str(file1), "start_line": 1, "end_line": 2},
                "metrics": {"cc": 1, "mi": 100.0, "smells": []},
            }
        ]
        analyze_results_2 = [
            {
                "id": "b",
                "source": {"file": str(file2), "start_line": 1, "end_line": 2},
                "metrics": {"cc": 1, "mi": 100.0, "smells": []},
            }
        ]

        with patch.object(static_analysis, "analyze_file", side_effect=[analyze_results_1, analyze_results_2]) as mock_analyze:
            results = static_analysis.analyze_files(str(base_dir), ["a.py", "b.py"])

            assert len(results) == 2
            assert results[0]["id"] == "a"
            assert results[1]["id"] == "b"

            assert mock_analyze.call_count == 2
            mock_analyze.assert_any_call(f"{base_dir}/a.py")
            mock_analyze.assert_any_call(f"{base_dir}/b.py")

    def test_analyze_files_skips_missing_files(self, tmp_path):
        base_dir = tmp_path

        with patch.object(static_analysis, "analyze_file", side_effect=FileNotFoundError), \
             patch.object(static_analysis, "logger") as mock_logger:

            results = static_analysis.analyze_files(str(base_dir), ["missing.py"])

            assert results == []
            mock_logger.warning.assert_called_once()
            assert "not found" in mock_logger.warning.call_args[0][0]
