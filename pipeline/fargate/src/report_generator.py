from logging import INFO, getLogger

from boto3 import client as boto3_client
from s3_handler import get_s3_bucket_name

logger = getLogger(__name__)
logger.setLevel(INFO)


def create_report(pr_number: str, results: list[dict]) -> dict:
    return {
        "pr_number": pr_number,
        "functions": [
            {
                "id": result["id"],
                "source": result["source"],
                "before": {
                    "code": result["before_code"],
                    "metrics": result["metrics"],
                },
                "after": {
                    "code": result["after_code"],
                },
                "test_results": None,
            }
            for result in results
        ]
    }


def generate_html(report: dict) -> str:
    pr_number = report["pr_number"]
    functions = report["functions"]

    rows = ""
    for func in functions:
        before = func.get("before", {})
        after = func.get("after", {})
        metrics = before.get("metrics", {})
        rows += f"""
        <tr>
            <td>{func["id"]}</td>
            <td><pre>{before.get("code", "N/A")}</pre></td>
            <td><pre>{after.get("code", "N/A")}</pre></td>
            <td>CC: {metrics.get("cc", "N/A")}<br>MI: {metrics.get("mi", "N/A")}</td>
            <td>pending</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><title>Report PR#{pr_number}</title></head>
<body>
    <h1>AI-CQ Pipeline Report - PR#{pr_number}</h1>
    <p>Test results: pending</p>
    <table border="1">
        <tr>
            <th>Function</th>
            <th>Before</th>
            <th>After</th>
            <th>Metrics</th>
            <th>Test Results</th>
        </tr>
        {rows}
    </table>
</body>
</html>"""


def save_report(pr_number: str, report: dict) -> str:
    s3 = boto3_client("s3")
    bucket = get_s3_bucket_name()
    key = f"reports/pr-{pr_number}/report.html"
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=generate_html(report).encode("utf-8"),
        ContentType="text/html",
    )
    logger.info(f"HTML report saved to S3 at {key}")
    return key


def load_report(pr_number: str) -> dict:
    s3 = boto3_client("s3")
    bucket = get_s3_bucket_name()
    key = f"reports/pr-{pr_number}/report.html"
    response = s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read().decode("utf-8")
