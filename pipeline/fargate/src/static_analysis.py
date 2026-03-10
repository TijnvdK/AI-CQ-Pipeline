from ast import Module, get_source_segment, parse as ast_parse, walk as ast_walk, FunctionDef, AsyncFunctionDef
from json import loads as json_loads
import logging
from subprocess import run as subprocess_run
from os import walk as os_walk
from typing import Any, Dict, List, Tuple, TypedDict

from radon.complexity import cc_visit
from radon.metrics import mi_visit

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class SourceLocation(TypedDict):
    file: str
    start_line: int
    end_line: int

class FunctionMetrics(TypedDict):
    cc: int
    mi: float
    smells: List[Dict[str, Any]]

class AnalysisResult(TypedDict):
    id: str
    source: SourceLocation
    metrics: FunctionMetrics

def load_ast(filepath: str) -> Tuple[Module, str]:
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()
    return ast_parse(source, filename=filepath), source


def get_functions(tree: Module, source: str) -> List[Dict]:
    functions = []
    for node in ast_walk(tree):
        if isinstance(node, (FunctionDef, AsyncFunctionDef)):
            source_segment = get_source_segment(source, node) or ""
            functions.append(
                {
                    "name": node.name,
                    "source": source_segment,
                    "start_line": node.lineno,
                    "end_line": node.end_lineno,
                }
            )
    return functions

def get_smells(results: List[AnalysisResult], filepath: str) -> List[AnalysisResult]:
    try:
        output = subprocess_run(
            ["pylint", filepath, "--output-format=json"],
            capture_output=True,
            text=True,
            timeout=60,
        )

        pylint_messages = json_loads(output.stdout) if output.stdout else []

    except Exception as e:
        logger.error(f"Error running pylint on {filepath}: {e}")
        pylint_messages = []

    for result in results:
        start = result["source"]["start_line"]
        end = result["source"]["end_line"]

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

        result["metrics"]["smells"] = function_smells

    return results


def analyze_file(filepath: str) -> List[AnalysisResult]:
    tree, source = load_ast(filepath)
    functions = get_functions(tree, source)

    results: List[AnalysisResult] = []

    for func in functions:
        cc = cc_visit(func["source"])
        mi = mi_visit(func["source"], multi=True)
        logger.info(f"Function {func['name']} - CC: {cc[0].complexity if cc else 'N/A'}, MI: {round(mi, 2) if mi else 'N/A'}")

        if not cc:
            continue

        results.append(
            AnalysisResult(
                id=func["name"],
                source=SourceLocation(
                    file=filepath,
                    start_line=func["start_line"],
                    end_line=func["end_line"],
                ),
                metrics=FunctionMetrics(
                    cc=cc[0].complexity,
                    mi=round(mi, 2),
                    smells=[],
                ),
            )
        )

    results = get_smells(results, filepath)

    return results

def analyze_dir(directory: str) -> List[AnalysisResult]:
    results = []

    for root, _, files in os_walk(directory):
        for file in files:
            if file.endswith(".py"):
                filepath = f"{root}/{file}"
                logger.info(f"Analyzing {filepath} ...")
                results.extend(analyze_file(filepath))

    return results
