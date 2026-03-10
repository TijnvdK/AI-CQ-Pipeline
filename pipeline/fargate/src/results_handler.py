from tempfile import NamedTemporaryFile
from typing import List, Optional, TypedDict
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
                after_analysis = analyze_file(tmp_path)
                after_metrics = [r["metrics"] for r in after_analysis]
            finally:
                os_unlink(tmp_path)

        before_after_metrics.append(BeforeAfterMetrics(
            **llm_result,
            before_metrics=before_metrics,
            after_metrics=after_metrics,
        ))

    return before_after_metrics