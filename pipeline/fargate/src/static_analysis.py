import ast
import json
import logging
import subprocess
from os import walk as os_walk
from typing import Dict, List

from radon.complexity import cc_visit
from radon.metrics import mi_visit

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Static Analysis Functions

def load_ast(filepath: str):
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()
    return ast.parse(source, filename=filepath), source


def get_functions(tree: ast.Module, source: str) -> List[Dict]:
    functions = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            source_segment = ast.get_source_segment(source, node) or ""
            functions.append(
                {
                    "name": node.name,
                    "source": source_segment,
                    "start_line": node.lineno,
                    "end_line": node.end_lineno,
                }
            )
    return functions

def get_smells(results: List[Dict], filepath: str) -> List[Dict]:
    try:
        output = subprocess.run(
            ["pylint", filepath, "--output-format=json"],
            capture_output=True,
            text=True,
            timeout=60,
        )

        pylint_messages = json.loads(output.stdout) if output.stdout else []

    except Exception as e:
        logger.exception("Failed to run pylint")
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

        result["smells"] = function_smells
        logger.info(f'Function {result["id"]} has the following smells: {function_smells}')

    return results


def analyze_file(filepath: str) -> List[Dict]:
    tree, source = load_ast(filepath)
    functions = get_functions(tree, source)

    results = []

    for func in functions:
        cc = cc_visit(func["source"])
        mi = mi_visit(func["source"], multi=True)
        logger.info(f"Function {func['name']} - CC: {cc[0].complexity if cc else 'N/A'}, MI: {round(mi, 2) if mi else 'N/A'}")

        if not cc:
            continue

        results.append(
            {
                "id": func["name"],
                "source": {
                    "file": filepath,
                    "start_line": func["start_line"],
                    "end_line": func["end_line"],
                },
                "metrics": {
                    "cc": cc[0].complexity,
                    "mi": round(mi, 2),
                },
                "smells": [],
            }
        )

    results = get_smells(results, filepath)

    return results

def analyze_dir(directory: str) -> List[Dict]:
    results = []

    for root, _, files in os_walk(directory):
        for file in files:
            if file.endswith(".py"):
                filepath = f"{root}/{file}"
                logger.info(f"Analyzing {filepath} ...")
                results.extend(analyze_file(filepath))

    return results
