import ast
import sys
import json
import subprocess


def load_ast(filepath: str) -> tuple[ast.Module, str]:
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source, filename=filepath)
    return tree, source


def get_functions(tree: ast.Module, source: str) -> list[dict]:
    functions = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            functions.append(
                {
                    "name": node.name,
                    "source": ast.get_source_segment(source, node),
                    "start_line": node.lineno,
                    "end_line": node.end_lineno,
                }
            )
    return functions


def get_complexity(functions: list[dict], filepath: str) -> list[dict]:
    from radon.complexity import cc_visit
    from radon.metrics import mi_visit

    results = []
    for func in functions:
        cc = cc_visit(func["source"])
        mi = mi_visit(func["source"], multi=True)
        if cc:
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
                        "smells": {"messages": []},
                    },
                }
            )
    return results


def get_smells(results: list[dict], filepath: str) -> list[dict]:
    output = subprocess.run(
        ["pylint", filepath, "--output-format=json"], capture_output=True, text=True
    )

    try:
        pylint_messages = json.loads(output.stdout)
    except json.JSONDecodeError:
        pylint_messages = []

    for result in results:
        start = result["source"]["start_line"]
        end = result["source"]["end_line"]

        messages = [
            {
                "line": msg["line"],
                "code": msg["message-id"],
                "message": msg["message"],
                "symbol": msg["symbol"],
            }
            for msg in pylint_messages
            if start <= msg["line"] <= end
        ]

        result["metrics"]["smells"] = messages

    return results


def write_jsonl(results: list[dict], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")


if __name__ == "__main__":
    filepath = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "output.jsonl"

    tree, source = load_ast(filepath)
    functions = get_functions(tree, source)
    results = get_complexity(functions, filepath)
    results = get_smells(results, filepath)

    write_jsonl(results, output_path)
    print(f"Written {len(results)} functions to {output_path}")
