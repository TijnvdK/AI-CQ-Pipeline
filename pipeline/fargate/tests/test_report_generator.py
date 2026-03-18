import sys
import types
from unittest.mock import Mock, patch

# 先伪造依赖模块，避免 import src.report_generator 时失败
fake_results_handler = types.ModuleType("results_handler")
fake_results_handler.BeforeAfterMetrics = dict

fake_s3_handler = types.ModuleType("s3_handler")
fake_s3_handler.save_html_file_to_s3 = Mock()

fake_static_analysis = types.ModuleType("static_analysis")
fake_static_analysis.FunctionMetrics = dict

sys.modules["results_handler"] = fake_results_handler
sys.modules["s3_handler"] = fake_s3_handler
sys.modules["static_analysis"] = fake_static_analysis

import src.report_generator as report_generator


class TestGenerateMetricHtml:
    def test_generate_metric_html_with_smells(self):
        metrics = {
            "cc": 7,
            "mi": 80,
            "smells": [
                {"message": "Long method"},
                {"message": "Too many branches"},
            ],
        }

        result = report_generator.generate_metric_html(metrics, "Function 1")

        assert 'class="metrics"' in result
        assert "Function 1" in result
        assert "Cyclomatic Complexity" in result
        assert "Maintainability Index" in result
        assert ">7<" in result
        assert ">80<" in result
        assert "Code Smells (2)" in result
        assert "<li>Long method</li>" in result
        assert "<li>Too many branches</li>" in result
        assert 'class="smells"' in result

    def test_generate_metric_html_with_no_smells(self):
        metrics = {
            "cc": 1,
            "mi": 99,
            "smells": [],
        }

        result = report_generator.generate_metric_html(metrics, "Function 1")

        assert "Code Smells (0)" in result
        assert "No code smells" in result
        assert 'class="no-smells"' in result

    def test_generate_metric_html_escapes_html_in_label_and_smells(self):
        metrics = {
            "cc": 3,
            "mi": 88,
            "smells": [
                {"message": "<script>alert(1)</script>"},
            ],
        }

        result = report_generator.generate_metric_html(metrics, '<b>Function X</b>')

        assert "&lt;b&gt;Function X&lt;/b&gt;" in result
        assert "<b>Function X</b>" not in result
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in result
        assert "<script>alert(1)</script>" not in result


class TestGenerateEntryHtml:
    def test_generate_entry_html_with_after_code_and_after_metrics(self):
        entry = {
            "source": {
                "file": "src/example.py",
                "start_line": 10,
                "end_line": 20,
            },
            "before_code": "def old():\n    return 1",
            "before_metrics": {
                "cc": 6,
                "mi": 82,
                "smells": [{"message": "Long method"}],
            },
            "after_code": "def old():\n    return 2",
            "after_metrics": [
                {
                    "cc": 2,
                    "mi": 95,
                    "smells": [],
                }
            ],
        }

        result = report_generator.generate_entry_html(entry, 0)

        assert "src/example.py: lines 10-20" in result
        assert "Before" in result
        assert "After" in result
        assert "def old():\n    return 1" in result
        assert "def old():\n    return 2" in result
        assert "No code smells" in result
        assert "Long method" in result

    def test_generate_entry_html_with_multiple_after_metrics_labels_functions(self):
        entry = {
            "source": {
                "file": "src/example.py",
                "start_line": 1,
                "end_line": 15,
            },
            "before_code": "def old():\n    pass",
            "before_metrics": {
                "cc": 8,
                "mi": 70,
                "smells": [],
            },
            "after_code": "def old():\n    helper()",
            "after_metrics": [
                {"cc": 2, "mi": 95, "smells": []},
                {"cc": 3, "mi": 91, "smells": []},
            ],
        }

        result = report_generator.generate_entry_html(entry, 0)

        assert "Function 1" in result
        assert "Function 2" in result

    def test_generate_entry_html_without_after_code(self):
        entry = {
            "source": {
                "file": "src/example.py",
                "start_line": 3,
                "end_line": 8,
            },
            "before_code": "def old():\n    pass",
            "before_metrics": {
                "cc": 5,
                "mi": 85,
                "smells": [],
            },
            "after_code": None,
            "after_metrics": None,
        }

        result = report_generator.generate_entry_html(entry, 0)

        assert "Before" in result
        assert "After" in result
        assert "No refactored version." in result

    def test_generate_entry_html_with_after_code_but_no_after_metrics(self):
        entry = {
            "source": {
                "file": "src/example.py",
                "start_line": 3,
                "end_line": 8,
            },
            "before_code": "def old():\n    pass",
            "before_metrics": {
                "cc": 5,
                "mi": 85,
                "smells": [],
            },
            "after_code": "def old():\n    return 1",
            "after_metrics": [],
        }

        result = report_generator.generate_entry_html(entry, 0)

        assert "def old():\n    return 1" in result
        assert "No after metrics." in result

    def test_generate_entry_html_escapes_html_in_file_path_and_code(self):
        entry = {
            "source": {
                "file": '<unsafe/file>.py',
                "start_line": 1,
                "end_line": 2,
            },
            "before_code": 'print("<tag>")',
            "before_metrics": {
                "cc": 1,
                "mi": 99,
                "smells": [],
            },
            "after_code": 'print("<after>")',
            "after_metrics": [
                {
                    "cc": 1,
                    "mi": 99,
                    "smells": [],
                }
            ],
        }

        result = report_generator.generate_entry_html(entry, 0)

        assert "&lt;unsafe/file&gt;.py" in result
        assert "<unsafe/file>.py" not in result
        assert 'print(&quot;&lt;tag&gt;&quot;)' in result
        assert 'print(&quot;&lt;after&gt;&quot;)' in result


class TestGenerateHtml:
    def test_generate_html_with_single_entry(self):
        entries = [
            {
                "source": {
                    "file": "src/example.py",
                    "start_line": 1,
                    "end_line": 3,
                },
                "before_code": "def a():\n    pass",
                "before_metrics": {
                    "cc": 5,
                    "mi": 85,
                    "smells": [],
                },
                "after_code": "def a():\n    return 1",
                "after_metrics": [
                    {
                        "cc": 2,
                        "mi": 95,
                        "smells": [],
                    }
                ],
            }
        ]

        result = report_generator.generate_html(entries, "My Report")

        assert "<!DOCTYPE html>" in result
        assert "<title>My Report</title>" in result
        assert "<h1>My Report</h1>" in result
        assert "1 function analyzed" in result
        assert "src/example.py: lines 1-3" in result

    def test_generate_html_with_multiple_entries_uses_plural(self):
        entries = [
            {
                "source": {
                    "file": "a.py",
                    "start_line": 1,
                    "end_line": 2,
                },
                "before_code": "def a(): pass",
                "before_metrics": {
                    "cc": 1,
                    "mi": 99,
                    "smells": [],
                },
                "after_code": None,
                "after_metrics": None,
            },
            {
                "source": {
                    "file": "b.py",
                    "start_line": 3,
                    "end_line": 5,
                },
                "before_code": "def b(): pass",
                "before_metrics": {
                    "cc": 2,
                    "mi": 98,
                    "smells": [],
                },
                "after_code": None,
                "after_metrics": None,
            },
        ]

        result = report_generator.generate_html(entries, "Another Report")

        assert "2 functions analyzed" in result
        assert "a.py: lines 1-2" in result
        assert "b.py: lines 3-5" in result

    def test_generate_html_escapes_title(self):
        entries = []
        result = report_generator.generate_html(entries, '<Report & Title>')

        assert "&lt;Report &amp; Title&gt;" in result
        assert "<Report & Title>" not in result


class TestCreateReport:
    def test_create_report_calls_s3_and_returns_url(self):
        before_after_metrics = [
            {
                "source": {
                    "file": "src/example.py",
                    "start_line": 1,
                    "end_line": 2,
                },
                "before_code": "def a(): pass",
                "before_metrics": {
                    "cc": 1,
                    "mi": 99,
                    "smells": [],
                },
                "after_code": None,
                "after_metrics": None,
            }
        ]

        with patch.object(
            report_generator,
            "save_html_file_to_s3",
            return_value="https://signed-url"
        ) as mock_save:
            result = report_generator.create_report("123", before_after_metrics)

            assert result == "https://signed-url"
            mock_save.assert_called_once()

            args = mock_save.call_args.args
            assert args[0] == "reports/pr_123_report.html"
            assert args[2] == "text/html"
            assert "Refactoring Report for PR#123" in args[1]
            assert "<!DOCTYPE html>" in args[1]