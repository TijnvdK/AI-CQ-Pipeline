from logging import getLogger
from typing import Any, List, Optional, TypedDict

from boto3 import client as boto3_client
from openai import OpenAI
from openai.types.chat import (ChatCompletionMessageParam,
                               ChatCompletionSystemMessageParam,
                               ChatCompletionUserMessageParam)

from static_analysis import AnalysisResult, FunctionMetrics, SourceLocation
from variables import PREFIX

ssm = boto3_client("ssm")

logger = getLogger(__name__)

# ========= AC 阈值 =========
CC_THRESHOLD = 5
MI_THRESHOLD = 85

# ========= OpenAI 配置 =========
MODEL = "gpt-5-mini"


# ========= Types =========
class FlaggedIssue(TypedDict):
    id: str
    source: SourceLocation
    before_code: str

class RefactoredResponse(TypedDict):
    source: SourceLocation
    before_code: str
    after_code: Optional[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_openai_api_token() -> str:
    try:
        response = ssm.get_parameter(Name=f"/{PREFIX}/openai-api-key", WithDecryption=True)
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


def is_out_of_bounds(metrics: FunctionMetrics) -> bool:
    cc = metrics.get("cc", 0)
    mi = metrics.get("mi", 100)
    sc = smells_count(metrics["smells"])
    return (cc > CC_THRESHOLD) or (mi < MI_THRESHOLD) or (sc > 0)

def extract_code_fragment(file_path: str, start_line: int, end_line: int) -> str:
    """
    CH: 按行号提取代码片段（1-based），用普通文件读取避免 linecache 缓存问题。
    EN: Extract code snippets by line number (1-based), and read them from a
        regular file to avoid linecache caching issues.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        all_lines = f.readlines()
    fragment = all_lines[start_line - 1 : end_line]
    return "".join(fragment)

def extract_codeblock(text: Optional[str]) -> Optional[str]:
    """
    CH: 从返回文本中提取 ```python ...``` 的代码块。
    EN: Extract the code block containing `python ...` from the returned text.
    """
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

def collect_flagged(sa_results: List[AnalysisResult]) -> List[FlaggedIssue]:
    """
    CH: 筛选超阈值的 issue，读取源码片段。
    EN: Filter issues exceeding the threshold and read source code snippets.
    """
    flagged: List[FlaggedIssue] = []
    for sa_result in sa_results:
        metrics = sa_result["metrics"]
        if not is_out_of_bounds(metrics):
            continue

        src = sa_result["source"]
        file_path = src.get("file", "")
        start_line = src.get("start_line", 0)
        end_line = src.get("end_line", start_line)

        original_code = extract_code_fragment(file_path, start_line, end_line)

        LOC = len(original_code.strip().splitlines())
        if LOC < 10:
            logger.info(f"Skipping {sa_result['id']} in {file_path} due to insufficient LOC ({LOC} lines).")
            continue

        custom_id = f"{file_path}:{sa_result['id']}"
        flagged.append(FlaggedIssue(
            id=custom_id,
            source=src,
            before_code=original_code
        ))

    return flagged


def build_messages(original_code: str) -> List[ChatCompletionMessageParam]:
    system_prompt = (
        "You are an expert software engineer. "
        "Return ONLY the refactored Python code wrapped in triple backticks with 'python' language identifier. "
        "Format your response exactly like this:\n\n"
        "```python\n"
        "# your refactored code here\n"
        "```\n\n"
        "You MUST preserve the original function's name and signature exactly as-is. "
        "You may extract logic into additional helper functions and call them from within the original function, "
        "but the original function's name and parameters must remain unchanged. "
        "Do not include any explanation, comments, or additional text outside the code block."
    )
    user_prompt = (
        f"With no explanation refactor the Python code to improve its quality:"
        f"\n\n```python\n{original_code}\n```"
    )
    system_message: ChatCompletionSystemMessageParam = {"role": "system", "content": system_prompt}
    user_message: ChatCompletionUserMessageParam = {"role": "user", "content": user_prompt}
    return [system_message, user_message]


def refactor_all(
    client: OpenAI,
    flagged: List[FlaggedIssue]
) -> List[RefactoredResponse]:
    """
    CH: 直接逐条调用 Chat Completions，返回 before/after 记录列表。
    EN: Call Chat Completions directly, one record at a time, to return a list
        of before/after records.
    """
    results: List[RefactoredResponse] = []
    total = len(flagged)

    for index, flagged_issue in enumerate(flagged):
        logger.info(f"[{index}/{total}] Processing issue: {flagged_issue['id']}")

        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=build_messages(flagged_issue["before_code"]),
                max_completion_tokens=32768,
            )
            after_code = extract_codeblock(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"[{index}/{total}] Error processing issue: {flagged_issue['id']}.\nError: {e}")
            after_code = None

        results.append(
            RefactoredResponse(
                source=flagged_issue["source"],
                before_code=flagged_issue["before_code"],
                after_code=after_code,
            )
        )

        logger.info(f"[{index}/{total}] Completed issue: {flagged_issue['id']}")

    return results

def refactor_issues_with_llm(sa_results: List[AnalysisResult]) -> List[RefactoredResponse]:
    if not sa_results:
        logger.info("No issues to refactor. Skipping LLM refactoring step.")
        return []

    flagged = collect_flagged(sa_results)
    if not flagged:
        logger.info("No issues exceeding the threshold. Skipping LLM refactoring step.")
        return []

    logger.info(f"Number of functions exceeding the threshold: {len(flagged)}, Start by calling OpenAI ...\n")

    client = OpenAI(api_key=get_openai_api_token())
    results = refactor_all(client, flagged)

    return results
