
import json
import os
import re
import base64
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

# ========= AC  =========
CC_THRESHOLD = 5
MI_THRESHOLD = 85

# ========= OpenAI set =========
MODEL = "gpt-5-mini"
QUALITY_ATTRIBUTE = "maintainability"

# ========= GitHub set =========
#
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_REF     = os.environ.get("REPO_REF", "main")


# ---------------------------------------------------------------------------
# GitHub URL  API request
# ---------------------------------------------------------------------------

def parse_github_url(github_url: str) -> Tuple[str, str, str]:
    url = github_url.strip()
    url = re.sub(r"\.git/", "/", url)
    url = re.sub(r"\.git$", "", url)

    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/blob/[^/]+/(.*)", url)
    if m:
        return m.group(1), m.group(2), m.group(3)

    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/(.*)", url)
    if m:
        return m.group(1), m.group(2), m.group(3)

    raise ValueError(f"cant use GitHub URL: {github_url}")


def build_api_url(owner: str, repo: str, file_path: str, ref: str = "main") -> str:
    file_path = file_path.lstrip("/")
    return f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}?ref={ref}"


def fetch_file_content(api_url: str, github_token: Optional[str] = None) -> Optional[str]:
    req = urllib.request.Request(api_url)
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "maintainability-fix-bot")
    if github_token:
        req.add_header("Authorization", f"token {github_token}")

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"GitHub API HTTP error {e.code}: {api_url}")
        return None
    except Exception as e:
        print(f"GitHub API request fail: {e}")
        return None

    encoded = data.get("content", "")
    if not encoded:
        return None

    try:
        return base64.b64decode(encoded.replace("\n", "")).decode("utf-8")
    except Exception as e:
        print(f"base64 code error: {e}")
        return None


def extract_lines(file_text: str, start_line: int, end_line: int) -> str:
    lines = file_text.splitlines(keepends=True)
    return "".join(lines[start_line - 1 : end_line])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def smells_count(smells: Any) -> int:
    if smells is None:
        return 0
    if isinstance(smells, list):
        return len(smells)
    if isinstance(smells, dict):
        return sum(smells.values())
    return 0


def is_out_of_bounds(metrics: Dict[str, Any]) -> bool:
    cc = metrics.get("cc", 0)
    mi = metrics.get("mi", 100)
    sc = smells_count(metrics.get("smells"))
    return (cc > CC_THRESHOLD) or (mi < MI_THRESHOLD) or (sc > 0)


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
# Core logic
# ---------------------------------------------------------------------------

def parse_issues_from_event(event: Dict[str, Any]) -> List[Dict[str, Any]]:


    if "body" in event:
        body = event["body"]
        if isinstance(body, str):
            body = body.strip()

            try:
                parsed = json.loads(body)
                if isinstance(parsed, list):
                    return parsed
                if "issues" in parsed:
                    return parsed["issues"]

                return [parsed]
            except json.JSONDecodeError:

                issues = []
                for line in body.splitlines():
                    line = line.strip()
                    if line:
                        issues.append(json.loads(line))
                return issues
        if isinstance(body, list):
            return body


    if "issues" in event:
        return event["issues"]


    if "source" in event:
        return [event]


    if isinstance(event, list):
        return event

    raise ValueError(f"Unable to parse issues from event. Please check the input format.")


def collect_flagged(
    issues: List[Dict[str, Any]],
    repo_ref: str,
    github_token: Optional[str],
) -> List[Tuple[str, Dict[str, Any], str, str]]:
    flagged = []
    file_cache: Dict[str, str] = {}

    for issue in issues:
        metrics = issue.get("metrics", {})
        if not is_out_of_bounds(metrics):
            continue

        src        = issue.get("source", {})
        github_url = src.get("file", "")
        if not github_url:
            continue

        start_line = int(src.get("start_line", 1))
        end_line   = int(src.get("end_line", start_line))

        try:
            owner, repo, file_path = parse_github_url(github_url)
        except ValueError as e:
            print(f"skip:{e}")
            continue

        api_url = build_api_url(owner, repo, file_path, repo_ref)

        if api_url not in file_cache:
            print(f"download: {owner}/{repo}/{file_path}")
            file_text = fetch_file_content(api_url, github_token)
            if file_text is None:
                print(f"Skip: Unable to retrieve file: {github_url}")
                continue
            file_cache[api_url] = file_text

        file_text     = file_cache[api_url]
        original_code = extract_lines(file_text, start_line, end_line).rstrip()

        if not original_code.strip():
            print(f"Skip: Extract to empty code: {github_url} line {start_line}-{end_line}")
            continue

        custom_id = (
            f"refactor_{issue.get('id', 'unknown')}"
            f"_{os.path.basename(file_path)}"
            f"_{start_line}_{end_line}"
        )
        flagged.append((custom_id, issue, original_code, api_url))

    return flagged


def build_messages(original_code: str, quality_attribute: str) -> List[Dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are an expert software engineer.\n"
                "Return ONLY a single Python code block wrapped in triple backticks like:\n"
                "```python\n<code>\n```\n"
                "No explanation, no additional text."
            )
        },
        {
            "role": "user",
            "content": (
                f"With no explanation refactor the Python code to improve its quality "
                f"and {quality_attribute}:\n\n{original_code}"
            )
        },
    ]


def refactor_all(
    client: OpenAI,
    flagged: List[Tuple[str, Dict[str, Any], str, str]],
    quality_attribute: str,
) -> List[Dict[str, Any]]:
    results = []

    for idx, (custom_id, issue, original_code, api_url) in enumerate(flagged, 1):
        src = issue.get("source", {})
        print(f"[{idx}/{len(flagged)}] Refactoring: {issue.get('id')} ({src.get('file', '')})")

        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=build_messages(original_code, quality_attribute),
                max_completion_tokens=2048,
            )
            after_text = response.choices[0].message.content
            after_code = extract_codeblock(after_text)
        except Exception as e:
            print(f"OpenAI Error: {e}")
            after_text = None
            after_code = None

        results.append({
            "custom_id":      custom_id,
            "id":             issue.get("id"),
            "source":         {**src, "github_api_url": api_url},
            "metrics":        issue.get("metrics", {}),
            "before_code":    original_code,
            "after_code":     after_code,
            "raw_after_text": after_text,
        })

    return results


# ---------------------------------------------------------------------------
# Lambda Handler
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    try:
        # 1. 从 event 解析 issues
        issues = parse_issues_from_event(event)
        print(f"received issues numbers：{len(issues)}")

        # 2. 筛选超阈值的函数，下载代码
        flagged = collect_flagged(issues, REPO_REF, GITHUB_TOKEN)
        if not flagged:
            return {
                "statusCode": 200,
                "body": json.dumps({"message": "There is no issue with exceeding the threshold; no processing is required.", "results": []}, ensure_ascii=False)
            }

        print(f"Number of functions exceeding the threshold：{len(flagged)}，Start calling OpenAI ...")


        client  = OpenAI()
        results = refactor_all(client, flagged, QUALITY_ATTRIBUTE)

        return {
            "statusCode": 200,
            "body": json.dumps({"results": results}, ensure_ascii=False)
        }

    except Exception as e:
        print(f"Lambda Error: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}, ensure_ascii=False)
        }
