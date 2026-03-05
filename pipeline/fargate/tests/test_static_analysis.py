import ast
import json

import pytest
from src.static_analysis import (get_complexity, get_functions, get_smells,
                                 load_ast, write_jsonl)

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
"""

# THIS IS NOT UPDATED

@pytest.fixture
def sample_file(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_CODE)
    return str(f)


def test_load_ast(sample_file):
    tree, source = load_ast(sample_file)
    assert isinstance(tree, ast.Module)
    assert "simple_function" in source


def test_get_functions(sample_file):
    tree, source = load_ast(sample_file)
    functions = get_functions(tree, source)
    names = [f["name"] for f in functions]
    assert len(functions) == 2
    assert "simple_function" in names
    assert "moderate_function" in names


def test_get_functions_have_required_fields(sample_file):
    tree, source = load_ast(sample_file)
    functions = get_functions(tree, source)
    for func in functions:
        assert "name" in func
        assert "source" in func
        assert "start_line" in func
        assert "end_line" in func


def test_get_complexity(sample_file):
    tree, source = load_ast(sample_file)
    functions = get_functions(tree, source)
    results = get_complexity(functions, sample_file)
    assert len(results) == 2
    for r in results:
        assert "cc" in r["metrics"]
        assert "mi" in r["metrics"]
        assert r["metrics"]["cc"] >= 1


def test_get_complexity_structure(sample_file):
    tree, source = load_ast(sample_file)
    functions = get_functions(tree, source)
    results = get_complexity(functions, sample_file)
    for r in results:
        assert "id" in r
        assert "source" in r
        assert "file" in r["source"]
        assert "start_line" in r["source"]
        assert "end_line" in r["source"]
        assert "metrics" in r


def test_get_smells(sample_file):
    tree, source = load_ast(sample_file)
    functions = get_functions(tree, source)
    results = get_complexity(functions, sample_file)
    results = get_smells(results, sample_file)
    for r in results:
        assert "smells" in r["metrics"]
        assert isinstance(r["metrics"]["smells"], list)


def test_write_jsonl(sample_file, tmp_path):
    tree, source = load_ast(sample_file)
    functions = get_functions(tree, source)
    results = get_complexity(functions, sample_file)

    print(results)

    output_path = str(tmp_path / "output.jsonl")
    write_jsonl(results, output_path)

    with open(output_path, "r") as f:
        lines = f.readlines()

    assert len(lines) == 2
    for line in lines:
        data = json.loads(line)
        assert "id" in data
        assert "metrics" in data
