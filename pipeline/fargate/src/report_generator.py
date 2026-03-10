from logging import INFO, getLogger
from typing import List
import html
from results_handler import BeforeAfterMetrics
from s3_handler import save_html_file_to_s3
from static_analysis import FunctionMetrics

logger = getLogger(__name__)
logger.setLevel(INFO)

def generate_metric_html(metrics: FunctionMetrics, functionLabel: str) -> str:
    cc = metrics["cc"]
    mi = metrics["mi"]
    smells = metrics.get("smells", [])
    smells_html = ""
    if smells:
        items = "".join(
            f'<li>{html.escape(str(s.get("message", s)))}</li>' for s in smells
        )
        smells_html = f'<ul class="smells">{items}</ul>'
    else:
        smells_html = '<p class="no-smells">No code smells</p>'

    return f"""
<div class="metrics">
    {f'<div class="metrics-label">{html.escape(functionLabel)}</div>'}
    <div class="metric-row">
        <span class="metric-name">Cyclomatic Complexity</span>
        <span class="badge">{cc}</span>
    </div>
    <div class="metric-row">
        <span class="metric-name">Maintainability Index</span>
        <span class="badge">{mi}</span>
    </div>
    <div class="smells-section">
        <span class="metric-name">Code Smells ({len(smells)})</span>
        {smells_html}
    </div>
</div>"""


def generate_entry_html(entry: BeforeAfterMetrics, index: int) -> str:
    src = entry["source"]
    loc = f'{html.escape(src["file"])}: lines {src["start_line"]}-{src["end_line"]}'

    before_code_html = f'<pre><code>{html.escape(entry["before_code"])}</code></pre>'

    after_code = entry.get("after_code")
    after_metrics = entry.get("after_metrics")

    if after_code is None:
        after_panel = """
<div class="panel after">
    <div class="panel-header">After</div>
    <p>No refactored version.</p>
</div>
"""
    else:
        after_code_html = f'<pre><code>{html.escape(after_code)}</code></pre>'
        after_metrics_html = ""
        if after_metrics:
            for idx, metric in enumerate(after_metrics):
                label = f"Function {idx+1}" if len(after_metrics) > 1 else ""
                after_metrics_html += generate_metric_html(metric, label)
        else:
            after_metrics_html = '<p>No after metrics.</p>'

        after_panel = f"""
<div class="panel after">
    <div class="panel-header">After</div>
    {after_code_html}
    {after_metrics_html}
</div>"""

    before_panel = f"""
<div class="panel before">
    <div class="panel-header">Before</div>
    {before_code_html}
    {generate_metric_html(entry["before_metrics"], "Function 1")}
</div>"""

    return f"""
<section class="entry">
    <p class="entry-loc">{loc}</p>
    <div class="panels">
        {before_panel}
        {after_panel}
    </div>
</section>"""


def generate_html(entries: List[BeforeAfterMetrics], title: str) -> str:
    body = "\n".join(generate_entry_html(e, i) for i, e in enumerate(entries))
    count = len(entries)

    return f"""<!DOCTYPE html>
<html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{html.escape(title)}</title>
        <style>
            *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

            :root {{
                /* Colors */
                --color-border: #000000;
                --color-bg-code: #000000;
                --color-text-code: #ffffff;
                --color-badge-bg: #8788bb;
                --color-badge-text: #ffffff;
                --color-smells: #ff0000;
                --color-no-smells: #00ff00;

                /* Typography */
                --font-base: 'IBM Plex Sans', system-ui, sans-serif;
                --font-mono: 'JetBrains Mono', monospace;
                --font-text-xs: 0.75rem;
                --font-text-base: 1rem;
                --font-text-2xl: 1.5rem;
                --tracking-tight: -0.025em;

                /* Spacing */
                --space-xs: 0.25rem;
                --space-sm: 0.5rem;
                --space-md: 0.75rem;
                --space-lg: 1rem;
                --space-xl: 1.25rem;
                --space-2xl: 2rem;
                --space-3xl: 2.5rem;

                /* Borders */
                --radius-md: 0.375rem;
                --border-width: 1px;

                /* Misc */
                --code-max-height: 320px;
            }}

            body {{
                font-family: var(--font-base);
                font-size: var(--font-size-base);
                padding: var(--space-2xl);
            }}

            header {{
                margin-bottom: var(--space-3xl);
                border-bottom: var(--border-width) solid var(--color-border);
                padding-bottom: var(--space-xl);
            }}

            header h1 {{
                font-size: var(--font-text-2xl);
                font-weight: 600;
                letter-spacing: var(--tracking-tight);
            }}

            header p {{
                margin-top: var(--space-sm);
                font-size: var(--font-text-base);
            }}

            .entry {{
                margin-bottom: var(--space-3xl);
            }}

            .entry-loc {{
                font-family: var(--font-mono);
                font-size: var(--font-text-xs);
                border: var(--border-width) solid var(--color-border);
                border-bottom: none;
                padding: var(--space-xs) var(--space-md);
                border-radius: var(--radius-md) var(--radius-md) 0 0;
            }}

            .panels {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 0;
                border: var(--border-width) solid var(--color-border);
                border-radius: 0 0 var(--radius-md) var(--radius-md);
                overflow: hidden;
            }}

            .panel {{
                padding: var(--space-lg);
                min-width: 0;
            }}

            .panel.before {{ border-right: var(--border-width) solid var(--color-border); }}

            .panel-header {{
                font-size: var(--font-text-xs);
                font-weight: 700;
                text-transform: uppercase;
                margin-bottom: var(--space-md);
                padding-bottom: var(--space-sm);
                border-bottom: var(--border-width) solid var(--color-border);
            }}

            pre {{
                background: var(--color-bg-code);
                border: var(--border-width) solid var(--color-border);
                border-radius: var(--radius-md);
                padding: var(--space-lg);
                overflow-x: auto;
                margin-bottom: var(--space-lg);
                max-height: var(--code-max-height);
            }}

            code {{
                font-family: var(--font-mono);
                font-size: var(--font-text-xs);
                color: var(--color-text-code);
                white-space: pre;
            }}

            .metrics {{
                display: flex;
                flex-direction: column;
                gap: var(--space-md);
            }}

            .metrics-label {{
                font-size: var(--font-text-xs);
                font-weight: 600;
                text-transform: uppercase;
                margin-bottom: var(--space-sm);
            }}

            .metric-row {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: var(--space-md);
            }}

            .metric-name {{
                font-size: var(--font-text-sm);
            }}

            .badge {{
                background: var(--color-badge-bg);
                color: var(--color-badge-text);
                font-size: var(--font-text-xs);
                font-weight: 600;
                padding: var(--space-xs) var(--space-sm);
                border-radius: var(--radius-md);
            }}

            .smells-section {{
                margin-top: var(--space-sm);
            }}

            .smells {{
                margin-top: var(--space-sm);
                padding-left: var(--space-md);
                font-size: var(--font-text-xs);
                color: var(--color-smells);
                display: flex;
                flex-direction: column;
                gap: var(--space-xs);
            }}

            .no-smells {{
                margin-top: var(--space-sm);
                font-size: var(--font-text-xs);
                color: var(--color-no-smells);
                display: flex;
                flex-direction: column;
                gap: var(--space-xs);
            }}

        </style>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    </head>
    <body>
        <header>
            <h1>{html.escape(title)}</h1>
            <p>{count} function{'s' if count != 1 else ''} analyzed</p>
        </header>
        {body}
    </body>
</html>"""

def create_report(pr_number: str, before_after_metrics: List[BeforeAfterMetrics]) -> str:
    report = generate_html(before_after_metrics, f"Refactoring Report for PR#{pr_number}")
    report_key = f"reports/pr_{pr_number}_report.html"

    private_url = save_html_file_to_s3(report_key, report, "text/html")
    return private_url
