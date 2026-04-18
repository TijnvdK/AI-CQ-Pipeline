from ast import (
    Module,
    get_source_segment,
    parse as ast_parse,
    walk as ast_walk,
    FunctionDef,
    AsyncFunctionDef,
)
from json import loads as json_loads
import logging
from subprocess import run as subprocess_run
from os import walk as os_walk
from tempfile import NamedTemporaryFile
import os
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

            # Include decorators in the extracted code
            start_line = node.lineno
            if node.decorator_list:
                # If decorators exist, start from the first decorator's line
                start_line = node.decorator_list[0].lineno

            functions.append(
                {
                    "name": node.name,
                    "source": source_segment,
                    "start_line": start_line,
                    "end_line": node.end_lineno,
                }
            )
    return functions


def get_smells(filepath: str) -> List[Dict[str, Any]]:
    try:
        output = subprocess_run(
            ["pylint", filepath, "--output-format=json"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return json_loads(output.stdout) if output.stdout else []
    except Exception as e:
        logger.error(f"Error running pylint on {filepath}: {e}")
        return []


def analyze_file(filepath: str, analyze_smells: bool = True) -> List[AnalysisResult]:
    tree, source = load_ast(filepath)
    functions = get_functions(tree, source)

    results: List[AnalysisResult] = []

    for func in functions:
        cc = cc_visit(func["source"])
        mi = mi_visit(func["source"], multi=True)
        logger.info(
            f"Function {func['name']} - CC: {cc[0].complexity if cc else 'N/A'}, MI: {round(mi, 2) if mi else 'N/A'}"
        )

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

    # Get pylint messages and append smells to results (if requested)
    if analyze_smells:
        pylint_messages = get_smells(filepath)
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


def analyze_cc(code: str) -> int:
    cc = cc_visit(code)
    logger.info(f"CC was done for the LLM output with a result of :{cc}")
    return cc


def analyze_mi(code: str) -> float:
    # logger.info(f"code sent to MI:\n```python\n{code}\n```")
    mi = mi_visit(code, multi=True)
    logger.info(f"MI was done for the LLM output with a result of: {mi}")
    return mi


def analyze_smells(code: str) -> Dict[str, List[Dict[str, Any]]]:
    try:
        # temp file for pylint
        with NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            temp_filepath = f.name

        try:
            tree, source = load_ast(temp_filepath)
            functions = get_functions(tree, source)

            if not functions:
                return {}

            pylint_messages = get_smells(temp_filepath)
            smells_by_function = {}

            for func in functions:
                start = func["start_line"]
                end = func["end_line"]

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
                smells_by_function[func["name"]] = function_smells

            logger.info(
                f"Code smells analyzed for {len(smells_by_function)} functions from LLM output"
            )
            return smells_by_function

        finally:
            os.unlink(temp_filepath)

    except Exception as e:
        logger.error(
            f"Error analyzing smells from code string (LLM output analysis): {e}"
        )
        return {}


def analyze_files(
    directory: str, relative_paths: List[str], analyze_smells: bool = True
) -> List[AnalysisResult]:
    results = []

    for rel_path in relative_paths:
        filepath = f"{directory}/{rel_path}"
        logger.info(f"Analyzing changed file {filepath} ...")
        try:
            results.extend(analyze_file(filepath, analyze_smells=analyze_smells))
        except FileNotFoundError:
            logger.warning(
                f"File {filepath} not found (possibly deleted in PR), skipping."
            )

    return results
