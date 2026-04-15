from collections import defaultdict
from tempfile import NamedTemporaryFile
from typing import Dict, List, Optional, TypedDict
from os import unlink as os_unlink
from logging import getLogger
from llm_handler import RefactoredResponse
from static_analysis import AnalysisResult, FunctionMetrics, SourceLocation, analyze_file

logger = getLogger(__name__)

class BeforeAfterMetrics(TypedDict):
    source: SourceLocation
    before_code: str
    after_code: Optional[str]
    before_metrics: FunctionMetrics
    after_metrics: Optional[List[FunctionMetrics]]

def get_before_vs_after_metrics(sa_results: List[AnalysisResult], llm_results: List[RefactoredResponse]) -> List[BeforeAfterMetrics]:
    before_after_metrics: List[BeforeAfterMetrics] = []

    sa_lookup = {
        (r["source"]["file"], r["source"]["start_line"], r["source"]["end_line"]): r["metrics"]
        for r in sa_results
    }

    for llm_result in llm_results:
        src = llm_result["source"]
        before_metrics = sa_lookup.get((src["file"], src["start_line"], src["end_line"]))
        if not before_metrics:
            logger.warning(f"No static analysis metrics found for {src}")
            continue

        after_metrics = None
        if llm_result["after_code"]:
            logger.info(f"Analyzing refactored code for {src}")
            with NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tmp:
                tmp.write(llm_result["after_code"])
                tmp_path = tmp.name

            try:
                # Analyze on full file context (no smells yet to avoid false positives from isolated function)
                after_analysis = analyze_file(tmp_path, analyze_smells=False)
                after_metrics = [r["metrics"] for r in after_analysis]

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

        before_after_metrics.append(BeforeAfterMetrics(
            **llm_result,
            before_metrics=before_metrics,
            after_metrics=after_metrics,
        ))

    return before_after_metrics

def apply_llm_changes(llm_results: List[RefactoredResponse]) -> int:
    changes_by_file: Dict[str, List[RefactoredResponse]] = defaultdict(list)
    for result in llm_results:
        if result["after_code"] is None:
            continue

        filepath = result["source"]["file"]
        changes_by_file[filepath].append(result)

    applied = 0
    for filepath, changes in changes_by_file.items():
        changes.sort(key=lambda c: c["source"]["start_line"], reverse=True)

        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for change in changes:
            start = change["source"]["start_line"] - 1 # Convert to 0-based index
            end = change["source"]["end_line"]

            # We have to do some weird indentation adjustments in the cases
            # that the functions are for example under a class or an if __name__ == "__main__" block,
            # because the LLM doesn't know the original indentation level
            original_indent = len(lines[start]) - len(lines[start].lstrip())
            indent_str = lines[start][:original_indent]

            after_lines = change["after_code"].splitlines(keepends=True)
            if after_lines:
                after_indent = len(after_lines[0]) - len(after_lines[0].lstrip())
                reindented = []
                for line in after_lines:
                    if line.strip():
                        stripped = line[after_indent:] if after_indent == 0 or line[:after_indent].isspace() else line.lstrip()
                        reindented.append(indent_str + stripped)
                    else:
                        reindented.append(line)

                if reindented and not reindented[-1].endswith("\n"):
                    reindented[-1] += "\n"
                after_lines = reindented

            lines[start:end] = after_lines
            applied += 1

        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(lines)

    logger.info(f"Applied {applied} LLM-generated refactorings to codebase.")
    return applied
