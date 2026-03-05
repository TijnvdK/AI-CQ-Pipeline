import argparse
import json
import os
from logging import getLogger
from typing import Any, Dict, List, Optional, Tuple

from boto3 import client as boto3_client
from openai import OpenAI

ssm = boto3_client("ssm")

logger = getLogger(__name__)

# ========= AC 阈值 =========
CC_THRESHOLD = 5
MI_THRESHOLD = 85

# ========= OpenAI 配置 =========
MODEL = "gpt-5-mini"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_openai_api_token():
    try:
        response = ssm.get_parameter(Name="/ai-cq-pipeline/openai-api-key", WithDecryption=True)
        return response["Parameter"]["Value"]
    except Exception as e:
        logger.error(f"Error retrieving OpenAI API token: {e}")
        raise

def smells_count(smells: Any) -> int:
    """
    兼容 smells 是 list / dict / None。
    BUG FIX: 原版用 len(dict)，只数种类数；
    改为 sum(values()) 统计实际 smell 总数。
    """
    if smells is None:
        return 0
    if isinstance(smells, list):
        return len(smells)
    if isinstance(smells, dict):
        return sum(smells.values())  # FIX: 原来是 len(smells)
    return 0


def is_out_of_bounds(metrics: Dict[str, Any]) -> bool:
    cc = metrics.get("cc", 0)
    mi = metrics.get("mi", 100)
    sc = smells_count(metrics.get("smells"))
    return (cc > CC_THRESHOLD) or (mi < MI_THRESHOLD) or (sc > 0)


def read_issues_jsonl(path: str) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            issues.append(json.loads(line))
    return issues


def resolve_source_path(source_file: str, base_dir: str) -> str:
    if os.path.isabs(source_file):
        return source_file
    return os.path.normpath(os.path.join(base_dir, source_file))


def extract_code_fragment(file_path: str, start_line: int, end_line: int) -> str:
    """按行号提取代码片段（1-based），用普通文件读取避免 linecache 缓存问题。"""
    with open(file_path, "r", encoding="utf-8") as f:
        all_lines = f.readlines()
    fragment = all_lines[start_line - 1 : end_line]
    return "".join(fragment)


def write_jsonl(path: str, rows: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def extract_codeblock(text: Optional[str]) -> Optional[str]:
    """从返回文本中提取 ```python ...``` 的代码块。"""
    if not text:
        return None
    start = text.find("```")
    if start == -1:
        return None
    end = text.rfind("```")
    if end <= start:
        return None
    block = text[start + 3 : end].strip()
    if block.lower().startswith("python"):
        block = block[6:].lstrip("\n")
    return block.strip()


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def collect_flagged(
    issues: List[Dict[str, Any]],
    issues_base_dir: str,
) -> List[Tuple[str, Dict[str, Any], str]]:
    """
    筛选超阈值的 issue，读取源码片段。
    返回 list of (custom_id, issue_dict, original_code)
    """
    flagged = []
    for issue in issues:
        metrics = issue.get("metrics", {})
        if not is_out_of_bounds(metrics):
            continue

        src = issue.get("source", {})
        src_file = src.get("file")
        if not src_file:
            continue

        start_line = int(src.get("start_line", 1))
        end_line   = int(src.get("end_line", start_line))
        abs_path   = resolve_source_path(src_file, issues_base_dir)

        if not os.path.exists(abs_path):
            print(f"⚠️  跳过：找不到源码文件: {abs_path}")
            continue

        original_code = extract_code_fragment(abs_path, start_line, end_line).rstrip()
        if not original_code.strip():
            print(f"⚠️  跳过：提取到空代码: {abs_path}:{start_line}-{end_line}")
            continue

        custom_id = (
            f"refactor_{issue.get('id', 'unknown')}"
            f"_{os.path.basename(abs_path)}"
            f"_{start_line}_{end_line}"
        )
        flagged.append((custom_id, issue, original_code))

    return flagged


def build_messages(original_code: str, quality_attribute: str) -> List[Dict[str, str]]:
    system_prompt = (
        "You are an expert software engineer. "
        "Refactor the given Python code to improve its quality. "
        "Return ONLY the refactored Python code wrapped in triple backticks with 'python' language identifier. "
        "Format your response exactly like this:\n\n"
        "```python\n"
        "# your refactored code here\n"
        "```\n\n"
        "Do not include any explanation, comments, or additional text outside the code block."
    )
    user_prompt = (
        f"With no explanation refactor the Python code to improve its quality "
        f"and {quality_attribute}:\n\n```python\n{original_code}\n```"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ]


def refactor_all(
    client: OpenAI,
    flagged: List[Tuple[str, Dict[str, Any], str]],
    quality_attribute: str,
    issues_base_dir: str,
) -> List[Dict[str, Any]]:
    """直接逐条调用 Chat Completions，返回 before/after 记录列表。"""
    results = []
    total = len(flagged)

    for idx, (custom_id, issue, original_code) in enumerate(flagged, 1):
        src = issue.get("source", {})
        abs_path = resolve_source_path(src.get("file", ""), issues_base_dir)
        logger.info(f"[{idx}/{total}] Rebuilding: {issue.get('id')}  ({abs_path})")

        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=build_messages(original_code, quality_attribute),
                max_completion_tokens=32768,
            )
            after_text = response.choices[0].message.content
            after_code = extract_codeblock(after_text)
        except Exception as e:
            logger.info(f"  ❌ fail: {e}")
            after_text = None
            after_code = None

        results.append({
            "custom_id":      custom_id,
            "id":             issue.get("id"),
            "source":         {**src, "abs_file": abs_path},
            "metrics":        issue.get("metrics", {}),
            "before_code":    original_code,
            "after_code":     after_code,
            "raw_after_text": after_text,
        })

        status = "✅" if after_code else "⚠️  （未能提取代码块）"
        logger.info(f"  {status}")

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--issues",            default="issues.jsonl")
    p.add_argument("--quality-attribute", default="maintainability",
                   help="提示词中的质量属性，如 maintainability / readability / performance")
    p.add_argument("--before-after",      default="before_after.jsonl",
                   help="before/after 关联输出 JSONL 路径")
    return p.parse_args()


def main():
    args = parse_args()

    issues_abs      = os.path.abspath(args.issues)
    issues_base_dir = os.path.dirname(issues_abs)

    issues = read_issues_jsonl(issues_abs)
    print(f"reading issues numbers: {len(issues)}")

    flagged = collect_flagged(issues, issues_base_dir)
    if not flagged:
        print("🎉 没有超阈值问题，无需处理。")
        return

    print(f"Number of functions exceeding the threshold {len(flagged)}, Start by calling OpenAI ...\n")

    client  = OpenAI(api_key=get_openai_api_token())  # 需要 OPENAI_API_KEY 环境变量
    results = refactor_all(client, flagged, args.quality_attribute, issues_base_dir)

    write_jsonl(args.before_after, results)
    print(f"\n✅ Generated: {args.before_after}({len(results)}  before/after)")


#     def refactor_issues_with_llm(
#     client: OpenAI,
#     issues: List[Dict[str, Any]],
#     quality_attribute: str,
#     base_dir: str,
# ) -> List[Dict[str, Any]]:
#     flagged = collect_flagged(issues, base_dir)
#     if not flagged:
#         return []
#     return refactor_all(client, flagged, quality_attribute, base_dir)

def refactor_issues_with_llm(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    args = parse_args()

    issues_abs = os.path.abspath(args.issues)
    issues_base_dir = os.path.dirname(issues_abs)
    logger.info(f"reading issues numbers：{len(issues)}")

    flagged = collect_flagged(issues, issues_base_dir)
    if not flagged:
        logger.info("🎉 No issues exceeding the threshold, no need to call OpenAI.")
        return []

    logger.info(f"Number of functions exceeding the threshold: {len(flagged)}, Start by calling OpenAI ...\n")

    client = OpenAI(api_key=get_openai_api_token())
    results = refactor_all(client, flagged, args.quality_attribute, issues_base_dir)

    write_jsonl(args.before_after, results)
    logger.info(f"\n✅ Generated:{args.before_after})({len(results)}  before/after)")

    return results
