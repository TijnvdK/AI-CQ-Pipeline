import os
from logging import getLogger
from typing import Any, List, Optional, TypedDict

from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from variables import PREFIX
from boto3 import client as boto3_client

ssm = boto3_client("ssm")

from provider import LLMProvider, get_provider
from static_analysis import (
    AnalysisResult,
    FunctionMetrics,
    SourceLocation,
    analyze_cc,
    analyze_mi,
    analyze_smells,
)

logger = getLogger(__name__)

# ========= 阈值 =========
CC_THRESHOLD = 5
MI_THRESHOLD = 85

# ========= 实验策略 =========
STRATEGY_ALL_AT_ONCE = "all_at_once"      # 实验 1：一次性全量优化
STRATEGY_ITERATIVE   = "iterative"        # 实验 2：逐项迭代优化


def get_openai_api_token() -> str:
    try:
        response = ssm.get_parameter(Name=f"/{PREFIX}/openai-api-key", WithDecryption=True)
        return response["Parameter"]["Value"]
    except Exception as e:
        logger.error(f"Error retrieving OpenAI API token: {e}")
        raise


# ========= Types =========

class FlaggedIssue(TypedDict):
    id: str
    source: SourceLocation
    before_code: str
    metrics: FunctionMetrics          # 新增：保留原始指标，方便后续判断


class RefactoredResponse(TypedDict):
    source: SourceLocation
    before_code: str
    after_code: Optional[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        return sum(smells.values())
    return 0


def is_out_of_bounds(metrics: FunctionMetrics) -> bool:
    cc = metrics.get("cc", 0)
    mi = metrics.get("mi", 100)
    sc = smells_count(metrics["smells"])
    return (cc > CC_THRESHOLD) or (mi < MI_THRESHOLD) or (sc > 0)


def _cc_exceeds(metrics: FunctionMetrics) -> bool:
    return metrics.get("cc", 0) > CC_THRESHOLD


def _mi_exceeds(metrics: FunctionMetrics) -> bool:
    return metrics.get("mi", 100) < MI_THRESHOLD


def _smells_exceed(metrics: FunctionMetrics) -> bool:
    return smells_count(metrics.get("smells")) > 0


def extract_code_fragment(file_path: str, start_line: int, end_line: int) -> str:
    with open(file_path, "r", encoding="utf-8") as f:
        all_lines = f.readlines()
    fragment = all_lines[start_line - 1 : end_line]
    return "".join(fragment)


def extract_codeblock(text: Optional[str]) -> Optional[str]:
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
# Targeted Prompts  （精准定向提示词）
# ---------------------------------------------------------------------------

_BASE_SYSTEM = (
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


def _prompt_all(original_code: str, metrics: FunctionMetrics) -> str:
    """实验 1 使用：一次性告知所有超阈值指标，让 LLM 一并优化。"""
    issues: List[str] = []
    cc = metrics.get("cc", 0)
    mi = metrics.get("mi", 100)
    sc = smells_count(metrics.get("smells"))

    if cc > CC_THRESHOLD:
        issues.append(f"- Cyclomatic Complexity (CC) is {cc}, which exceeds the threshold of {CC_THRESHOLD}. "
                       "Reduce branching by extracting helper functions, using early returns, or simplifying conditions.")
    if mi < MI_THRESHOLD:
        issues.append(f"- Maintainability Index (MI) is {mi:.1f}, below the threshold of {MI_THRESHOLD}. "
                       "Improve readability by shortening the function, reducing nesting, and using clear naming.")
    if sc > 0:
        smell_detail = metrics.get("smells", {})
        issues.append(f"- Code smells detected ({sc} total): {smell_detail}. "
                       "Remove the identified code smells while keeping behaviour unchanged.")

    issue_block = "\n".join(issues)
    return (
        f"The following function has these specific quality issues:\n{issue_block}\n\n"
        f"Refactor ONLY to fix the issues listed above. Do NOT make unrelated changes.\n\n"
        f"```python\n{original_code}\n```"
    )


def _prompt_cc(original_code: str, cc_value: int) -> str:
    """CC 专项优化提示词。"""
    return (
        f"The following function has a Cyclomatic Complexity (CC) of {cc_value}, "
        f"which exceeds the acceptable threshold of {CC_THRESHOLD}.\n\n"
        "Refactor the function to reduce its cyclomatic complexity. Strategies:\n"
        "- Extract complex conditional branches into helper functions\n"
        "- Use early returns to reduce nesting depth\n"
        "- Replace nested if/elif chains with lookup tables or polymorphism where appropriate\n\n"
        "Do NOT change the function signature. Do NOT fix other issues.\n\n"
        f"```python\n{original_code}\n```"
    )


def _prompt_mi(original_code: str, mi_value: float) -> str:
    """MI 专项优化提示词。"""
    return (
        f"The following function has a Maintainability Index (MI) of {mi_value:.1f}, "
        f"which is below the acceptable threshold of {MI_THRESHOLD}.\n\n"
        "Refactor to improve maintainability. Strategies:\n"
        "- Break long functions into smaller, well-named helpers\n"
        "- Reduce nesting depth\n"
        "- Improve variable and parameter naming for clarity\n"
        "- Simplify overly complex expressions\n\n"
        "Do NOT change the function signature. Do NOT fix other issues.\n\n"
        f"```python\n{original_code}\n```"
    )


def _prompt_smells(original_code: str, smells: Any) -> str:
    """Code Smells 专项优化提示词。"""
    return (
        f"The following function contains these code smells: {smells}\n\n"
        "Refactor to remove the identified code smells while preserving the exact same behaviour. "
        "Focus only on eliminating the smells listed above.\n\n"
        "Do NOT change the function signature. Do NOT fix other issues.\n\n"
        f"```python\n{original_code}\n```"
    )


def build_messages(original_code: str) -> List[ChatCompletionMessageParam]:
    """保留原接口：通用全量提示词（向后兼容）。"""
    system_message: ChatCompletionSystemMessageParam = {"role": "system", "content": _BASE_SYSTEM}
    user_message: ChatCompletionUserMessageParam = {
        "role": "user",
        "content": (
            "With no explanation refactor the Python code to improve its quality:"
            f"\n\n```python\n{original_code}\n```"
        ),
    }
    return [system_message, user_message]


def _call_provider(provider: LLMProvider, user_prompt: str) -> Optional[str]:
    """封装 provider 调用：传入定向 user_prompt，系统提示词由 provider 内部的 _BASE_SYSTEM 提供。"""
    try:
        return provider.complete_with_prompt(user_prompt)
    except Exception as e:
        logger.error(f"Provider call failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def collect_flagged(sa_results: List[AnalysisResult]) -> List[FlaggedIssue]:
    """筛选超阈值的 issue，读取源码片段。"""
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
            before_code=original_code,
            metrics=metrics,
        ))

    return flagged


# ---- 实验 1：一次性全量优化 ----

def refactor_all_at_once(
    provider: LLMProvider,
    flagged: List[FlaggedIssue],
) -> List[RefactoredResponse]:
    """
    实验 1 — All-at-once：将所有超阈值指标一次性告知 LLM，让其一并优化。
    """
    results: List[RefactoredResponse] = []
    total = len(flagged)

    for idx, issue in enumerate(flagged):
        logger.info(f"[All-at-once {idx+1}/{total}] Processing: {issue['id']}")

        user_prompt = _prompt_all(issue["before_code"], issue["metrics"])
        after_code = _call_provider(provider, user_prompt)

        results.append(RefactoredResponse(
            source=issue["source"],
            before_code=issue["before_code"],
            after_code=after_code,
        ))
        logger.info(f"[All-at-once {idx+1}/{total}] Done: {issue['id']}")

    return results


# ---- 实验 2：逐项迭代优化 ----

def refactor_iterative(
    provider: LLMProvider,
    flagged: List[FlaggedIssue],
) -> List[RefactoredResponse]:
    """
    实验 2 — Iterative：按 CC → MI → Smells 的顺序逐项优化。
    每一轮优化后重新检测指标，只在仍超阈值时继续下一轮。
    """
    results: List[RefactoredResponse] = []
    total = len(flagged)

    for idx, issue in enumerate(flagged):
        logger.info(f"[Iterative {idx+1}/{total}] Processing: {issue['id']}")

        current_code = issue["before_code"]
        current_metrics = issue["metrics"]

        # --- Step 1: CC ---
        if _cc_exceeds(current_metrics):
            cc_val = current_metrics.get("cc", 0)
            logger.info(f"  [CC] CC={cc_val} > {CC_THRESHOLD}, optimizing ...")
            prompt = _prompt_cc(current_code, cc_val)
            result = _call_provider(provider, prompt)
            if result:
                current_code = result
                current_metrics = _reanalyze(current_code, current_metrics)
        else:
            logger.info("  [CC] Within threshold, skipping.")

        # --- Step 2: MI ---
        if _mi_exceeds(current_metrics):
            mi_val = current_metrics.get("mi", 100)
            logger.info(f"  [MI] MI={mi_val:.1f} < {MI_THRESHOLD}, optimizing ...")
            prompt = _prompt_mi(current_code, mi_val)
            result = _call_provider(provider, prompt)
            if result:
                current_code = result
                current_metrics = _reanalyze(current_code, current_metrics)
        else:
            logger.info("  [MI] Within threshold, skipping.")

        # --- Step 3: Code Smells ---
        if _smells_exceed(current_metrics):
            smells = current_metrics.get("smells")
            logger.info(f"  [Smells] {smells_count(smells)} smell(s) detected, optimizing ...")
            prompt = _prompt_smells(current_code, smells)
            result = _call_provider(provider, prompt)
            if result:
                current_code = result
        else:
            logger.info("  [Smells] No smells, skipping.")

        # 最终结果
        after_code = current_code if current_code != issue["before_code"] else None
        results.append(RefactoredResponse(
            source=issue["source"],
            before_code=issue["before_code"],
            after_code=after_code,
        ))
        logger.info(f"[Iterative {idx+1}/{total}] Done: {issue['id']}")

    return results


def _reanalyze(code: str, fallback_metrics: FunctionMetrics) -> FunctionMetrics:
    """
    对优化后的代码重新跑静态分析，返回新指标。
    分别调用 analyze_cc / analyze_mi / analyze_smells。
    任何一项失败则沿用 fallback 中对应的值。
    """
    try:
        cc = analyze_cc(code)
    except Exception as e:
        logger.warning(f"Re-analysis CC failed: {e}")
        cc = fallback_metrics.get("cc", 0)

    try:
        mi = analyze_mi(code)
    except Exception as e:
        logger.warning(f"Re-analysis MI failed: {e}")
        mi = fallback_metrics.get("mi", 100.0)

    try:
        smells = analyze_smells(code)
    except Exception as e:
        logger.warning(f"Re-analysis smells failed: {e}")
        smells = fallback_metrics.get("smells", [])

    return FunctionMetrics(cc=cc, mi=mi, smells=smells)


# ---------------------------------------------------------------------------
# Entry point（入口不变，外部调用方式兼容）
# ---------------------------------------------------------------------------

def refactor_all(
    provider: LLMProvider,
    flagged: List[FlaggedIssue],
) -> List[RefactoredResponse]:
    """
    根据环境变量 REFACTOR_STRATEGY 选择实验策略。
      - "all_at_once"  → 实验 1（默认）
      - "iterative"    → 实验 2
    """
    strategy = os.environ.get("REFACTOR_STRATEGY", STRATEGY_ALL_AT_ONCE).lower()
    logger.info(f"Refactoring strategy: {strategy}")

    if strategy == STRATEGY_ITERATIVE:
        return refactor_iterative(provider, flagged)
    else:
        return refactor_all_at_once(provider, flagged)


def refactor_issues_with_llm(sa_results: List[AnalysisResult]) -> List[RefactoredResponse]:
    """入口函数，签名不变，外部调用不需要任何修改。"""
    if not sa_results:
        logger.info("No issues to refactor. Skipping LLM refactoring step.")
        return []

    flagged = collect_flagged(sa_results)
    if not flagged:
        logger.info("No issues exceeding the threshold. Skipping LLM refactoring step.")
        return []

    logger.info(f"Number of functions exceeding the threshold: {len(flagged)}, starting LLM refactoring ...\n")

    provider = get_provider()
    return refactor_all(provider, flagged)
