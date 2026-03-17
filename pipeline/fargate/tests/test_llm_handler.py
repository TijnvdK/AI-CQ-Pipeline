import os
os.environ["AWS_DEFAULT_REGION"] = "eu-north-1"

import pytest
from unittest.mock import MagicMock, mock_open, patch
from src.llm_handler import (
    smells_count,
    is_out_of_bounds,
    extract_codeblock,
    extract_code_fragment,
    collect_flagged,
    build_messages,
    refactor_all,
    get_openai_api_token,
    refactor_issues_with_llm,
)


class TestSmellsCount:
    def test_none_returns_zero(self):
        assert smells_count(None) == 0

    def test_empty_list(self):
        assert smells_count([]) == 0

    def test_list_counts_items(self):
        assert smells_count(["long_method", "god_class", "dead_code"]) == 3

    def test_empty_dict(self):
        assert smells_count({}) == 0

    def test_dict_sums_values(self):
        assert smells_count({"long_method": 3, "dead_code": 2}) == 5

    def test_dict_single_category_multiple_occurrences(self):
        assert smells_count({"long_method": 10}) == 10

    def test_unknown_type_returns_zero(self):
        assert smells_count(42) == 0
        assert smells_count("bad_input") == 0


class TestIsOutOfBounds:
    def _make_metrics(self, cc=0, mi=100, smells=None):
        return {"cc": cc, "mi": mi, "smells": smells}

    def test_all_good_returns_false(self):
        assert is_out_of_bounds(self._make_metrics(cc=3, mi=90)) is False

    def test_high_cc_triggers(self):
        assert is_out_of_bounds(self._make_metrics(cc=6)) is True

    def test_cc_at_threshold_ok(self):
        assert is_out_of_bounds(self._make_metrics(cc=5)) is False

    def test_low_mi_triggers(self):
        assert is_out_of_bounds(self._make_metrics(mi=84)) is True

    def test_mi_at_threshold_ok(self):
        assert is_out_of_bounds(self._make_metrics(mi=85)) is False

    def test_smells_triggers(self):
        assert is_out_of_bounds(self._make_metrics(smells=["long_method"])) is True

    def test_all_bad_triggers(self):
        assert is_out_of_bounds(self._make_metrics(cc=10, mi=50, smells={"x": 3})) is True


class TestExtractCodeblock:
    def test_none_returns_none(self):
        assert extract_codeblock(None) is None

    def test_empty_string_returns_none(self):
        assert extract_codeblock("") is None

    def test_no_backticks_returns_none(self):
        assert extract_codeblock("just plain text") is None

    def test_extracts_python_block(self):
        text = "Here is code:\n```python\ndef foo():\n    pass\n```"
        assert extract_codeblock(text) == "def foo():\n    pass"

    def test_extracts_plain_backtick_block(self):
        text = "```\ndef bar():\n    return 1\n```"
        assert extract_codeblock(text) == "def bar():\n    return 1"

    def test_single_backtick_group_returns_content(self):
        # 源码行为：start 和 end 找到同一对 ``` 的首尾，仍会提取内容
        assert extract_codeblock("```only one```") == "only one"


class TestExtractCodeFragment:
    def test_extracts_correct_lines(self):
        file_content = "line1\nline2\nline3\nline4\nline5\n"
        with patch("builtins.open", mock_open(read_data=file_content)):
            result = extract_code_fragment("dummy.py", 2, 4)
        assert result == "line2\nline3\nline4\n"

    def test_single_line(self):
        file_content = "alpha\nbeta\ngamma\n"
        with patch("builtins.open", mock_open(read_data=file_content)):
            result = extract_code_fragment("dummy.py", 2, 2)
        assert result == "beta\n"


class TestCollectFlagged:
    def _make_sa_result(self, cc=10, mi=50, smells=None, file="foo.py", start=1, end=20, id="fn_a"):
        return {
            "id": id,
            "source": {"file": file, "start_line": start, "end_line": end},
            "metrics": {"cc": cc, "mi": mi, "smells": smells or []},
        }

    def _make_code(self, num_lines=15):
        return "\n".join(f"    line_{i} = {i}" for i in range(num_lines)) + "\n"

    def test_skips_results_within_bounds(self):
        assert collect_flagged([self._make_sa_result(cc=1, mi=95, smells=[])]) == []

    def test_skips_short_functions(self):
        short_code = "def f():\n    pass\n"
        with patch("src.llm_handler.extract_code_fragment", return_value=short_code):
            assert collect_flagged([self._make_sa_result()]) == []

    def test_includes_long_flagged_function(self):
        long_code = self._make_code(15)
        with patch("src.llm_handler.extract_code_fragment", return_value=long_code):
            result = collect_flagged([self._make_sa_result(file="bar.py", id="fn_b")])
        assert len(result) == 1
        assert result[0]["id"] == "bar.py:fn_b"
        assert result[0]["before_code"] == long_code

    def test_empty_input(self):
        assert collect_flagged([]) == []

    def test_multiple_mixed(self):
        long_code = self._make_code(15)
        with patch("src.llm_handler.extract_code_fragment", return_value=long_code):
            result = collect_flagged([
                self._make_sa_result(cc=1, mi=95, id="good"),
                self._make_sa_result(cc=10, id="bad"),
            ])
        assert len(result) == 1
        assert "bad" in result[0]["id"]


class TestBuildMessages:
    def test_returns_two_messages(self):
        assert len(build_messages("def foo(): pass")) == 2

    def test_system_message_role(self):
        assert build_messages("def foo(): pass")[0]["role"] == "system"

    def test_user_message_contains_code(self):
        code = "def my_func(): pass"
        assert code in build_messages(code)[1]["content"]

    def test_system_prompt_mentions_preserve_signature(self):
        assert "signature" in build_messages("x = 1")[0]["content"].lower()


class TestRefactorAll:
    def _make_flagged(self, id="a.py:fn", code="def f(): pass"):
        return {
            "id": id,
            "source": {"file": "a.py", "start_line": 1, "end_line": 5},
            "before_code": code,
        }

    def _make_client(self, content="```python\ndef f(): pass\n```"):
        client = MagicMock()
        choice = MagicMock()
        choice.message.content = content
        client.chat.completions.create.return_value = MagicMock(choices=[choice])
        return client

    def test_happy_path_returns_after_code(self):
        results = refactor_all(self._make_client(), [self._make_flagged()])
        assert len(results) == 1
        assert results[0]["after_code"] is not None

    def test_api_error_sets_after_code_none(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("API error")
        results = refactor_all(client, [self._make_flagged()])
        assert results[0]["after_code"] is None

    def test_empty_flagged_returns_empty(self):
        assert refactor_all(self._make_client(), []) == []

    def test_preserves_source_and_before_code(self):
        results = refactor_all(self._make_client(), [self._make_flagged(code="original code")])
        assert results[0]["before_code"] == "original code"
        assert results[0]["source"]["file"] == "a.py"

    def test_multiple_issues_all_processed(self):
        flagged = [self._make_flagged(id=f"f{i}") for i in range(5)]
        assert len(refactor_all(self._make_client(), flagged)) == 5


class TestGetOpenaiApiToken:
    def test_returns_token_on_success(self):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "sk-test-token"}}
        with patch("src.llm_handler.boto3_client", return_value=mock_ssm), \
             patch("src.llm_handler.ssm", None), \
             patch.dict("os.environ", {}, clear=False):
            assert get_openai_api_token() == "sk-test-token"

    def test_raises_on_ssm_error(self):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.side_effect = Exception("SSM error")
        with patch("src.llm_handler.boto3_client", return_value=mock_ssm), \
             patch("src.llm_handler.ssm", None), \
             patch.dict("os.environ", {}, clear=False):
            with pytest.raises(Exception, match="SSM error"):
                get_openai_api_token()


class TestRefactorIssuesWithLlm:
    def test_empty_input_returns_empty(self):
        assert refactor_issues_with_llm([]) == []

    def test_no_flagged_issues_returns_empty(self):
        good_result = {
            "id": "fn_a",
            "source": {"file": "a.py", "start_line": 1, "end_line": 5},
            "metrics": {"cc": 1, "mi": 95, "smells": []},
        }
        assert refactor_issues_with_llm([good_result]) == []

    def test_end_to_end_with_mocks(self):
        sa_result = {
            "id": "fn_b",
            "source": {"file": "b.py", "start_line": 1, "end_line": 20},
            "metrics": {"cc": 10, "mi": 50, "smells": []},
        }
        long_code = "\n".join(f"    x_{i} = {i}" for i in range(15))
        mock_choice = MagicMock()
        mock_choice.message.content = "```python\ndef fn_b(): pass\n```"

        with patch("src.llm_handler.extract_code_fragment", return_value=long_code), \
             patch("src.llm_handler.get_openai_api_token", return_value="sk-fake"), \
             patch("src.llm_handler.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
            MockOpenAI.return_value = mock_client
            results = refactor_issues_with_llm([sa_result])

        assert len(results) == 1
        assert results[0]["after_code"] == "def fn_b(): pass"