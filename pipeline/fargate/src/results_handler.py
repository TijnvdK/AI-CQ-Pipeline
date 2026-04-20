from collections import defaultdict
from tempfile import NamedTemporaryFile
from typing import Dict, List, Optional, TypedDict
from os import unlink as os_unlink
from logging import getLogger
from llm_handler import RefactoredResponse
from static_analysis import (
    AnalysisResult,
    FunctionMetrics,
    SourceLocation,
    analyze_file,
    get_smells,
)

logger = getLogger(__name__)


class BeforeAfterMetrics(TypedDict):
    source: SourceLocation
    before_code: str
    after_code: Optional[str]
    before_metrics: FunctionMetrics
    after_metrics: Optional[List[FunctionMetrics]]


def apply_refactored_code(
    original_lines: List[str], change: RefactoredResponse
) -> List[str]:
    """
    ReturnReturn a copy of original_lines with the function at change["source"] replaced
    by change["after_code"], reindented to match the original indentation level.

    Args:
        original_lines (List[str]):
        change (RefactoredResponse): _description_

    Returns:
        List[str]: _description_
    """
    start = change["source"]["start_line"] - 1  # Convert to 0-based index
    end = change["source"]["end_line"]

    # We have to do some weird indentation adjustments in the cases
    # that the functions are for example under a class or an if __name__ == "__main__" block,
    # because the LLM doesn't know the original indentation level
    original_indent = len(original_lines[start]) - len(original_lines[start].lstrip())
    indent_str = original_lines[start][:original_indent]

    after_lines = change["after_code"].splitlines(keepends=True)
    if after_lines:
        # Calculate the minimum indentation from all non-empty lines
        # This handles cases where the first line might have different indentation
        # change was done here. problem with indents
        non_empty_indents = [
            len(line) - len(line.lstrip()) for line in after_lines if line.strip()
        ]
        after_indent = min(non_empty_indents) if non_empty_indents else 0

        reindented = []
        for line in after_lines:
            if line.strip():
                current_indent = len(line) - len(line.lstrip())
                relative_indent = max(0, current_indent - after_indent)
                reindented.append(indent_str + " " * relative_indent + line.lstrip())
            else:
                reindented.append(line)

        if reindented and not reindented[-1].endswith("\n"):
            reindented[-1] += "\n"
        after_lines = reindented

    result = original_lines[:]
    result[start:end] = after_lines
    return result


def apply_llm_changes(llm_results: List[RefactoredResponse]) -> int:
    changes_by_file: Dict[str, List[RefactoredResponse]] = defaultdict(list)
    for result in llm_results:
        if result["after_code"] is None:
            continue
        changes_by_file[result["source"]["file"]].append(result)

    applied = 0
    for filepath, changes in changes_by_file.items():
        # Process bottom-up so earlier line numbers stay valid
        changes.sort(key=lambda c: c["source"]["start_line"], reverse=True)

        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for change in changes:
            lines = apply_refactored_code(lines, change)
            applied += 1

        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(lines)
            # Always add a final newline at the end of the file.
            if not lines[-1].endswith("\n"):
                f.write("\n")

    logger.info(f"Applied {applied} LLM-generated refactorings to codebase.")
    return applied


def get_before_vs_after_metrics(
    sa_results: List[AnalysisResult], llm_results: List[RefactoredResponse]
) -> List[BeforeAfterMetrics]:
    before_after_metrics: List[BeforeAfterMetrics] = []

    sa_lookup = {
        (r["source"]["file"], r["source"]["start_line"], r["source"]["end_line"]): r[
            "metrics"
        ]
        for r in sa_results
    }

    for llm_result in llm_results:
        src = llm_result["source"]
        before_metrics = sa_lookup.get(
            (src["file"], src["start_line"], src["end_line"])
        )
        if not before_metrics:
            logger.warning(f"No static analysis metrics found for {src}")
            continue

        after_metrics = None
        if llm_result["after_code"]:
            logger.info(f"Analyzing refactored code for {src}")

            try:

                with open(src["file"], "r", encoding="utf-8") as f:
                    original_lines = f.readlines()

                full_file_lines = apply_refactored_code(original_lines, llm_result)

                with NamedTemporaryFile(
                    mode="w", suffix=".py", delete=False, encoding="utf-8"
                ) as tmp:
                    tmp.writelines(full_file_lines)
                    tmp.flush()
                    tmp_path = tmp.name

                try:
                    # Analyze on full file context (no smells yet to avoid false positives from isolated function)
                    splice_start = src["start_line"]
                    splice_end = (
                        src["start_line"]
                        + len(llm_result["after_code"].splitlines())
                        - 1
                    )

                    all_analysis = analyze_file(tmp_path, analyze_smells=False)
                    after_analysis = [
                        r
                        for r in all_analysis
                        if r["source"]["start_line"] >= splice_start
                        and r["source"]["end_line"] <= splice_end
                    ]
                    after_metrics = [r["metrics"] for r in after_analysis]
                    logger.info(
                        f"It reached here, so it has already has done MI and CC"
                    )

                    # Now run smells analysis on the full file and extract per-function smells
                    pylint_messages = get_smells(tmp_path)
                    for idx, analysis_result in enumerate(after_analysis):
                        start = analysis_result["source"]["start_line"]
                        end = analysis_result["source"]["end_line"]

                        function_smells = [
                            {
                                "line": msg["line"],
                                "code": msg["message-id"],
                                "message": msg["message"],
                                "symbol": msg["symbol"],
                            }
                            for msg in pylint_messages
                            if start <= msg["line"] <= end
                        ]
                        after_metrics[idx]["smells"] = function_smells
                finally:
                    os_unlink(tmp_path)

            except Exception as e:
                logger.error(f"Error analyzing refactored code for {src}: {e}")
                logger.error(
                    f'Original code:\n{llm_result["before_code"]}\nRefactored code:\n{llm_result["after_code"]}'
                )
                raise e

        before_after_metrics.append(
            BeforeAfterMetrics(
                **llm_result,
                before_metrics=before_metrics,
                after_metrics=after_metrics,
            )
        )

    return before_after_metrics
