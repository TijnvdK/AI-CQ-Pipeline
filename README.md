# **AI-CQ-Pipeline** (AI Code Quality Pipeline): Automated Software Quality Analysis and Repair in CI/CD

A pipeline-driven system that is triggered by pull requests to automatically analyze and improve code quality. 

## Overview

The pipeline first analyzes changed Python functions for code quality issues using **Radon** to measure Cyclomatic Complexity and Maintainability Index and **Pylint** for code smells. Functions that exceed quality thresholds are passed to an LLM, which generates refactored code. The fixes are then pushed to an `autofix/pr-{number}` branch, and the repository's pytest suite is run to verify correctness. Finally, an HTML report with before/after metrics is shared via a link in a PR comment, valid for seven days.
The LLM provider, quality thresholds, and prompting strategy are configurable in `pipeline/fargate/src/llm_handler`.


## Requirements

- Python 3.13
- AWS account 
- GitHub repository
- Ansible 2.12

Install Python tooling:

```bash
python3 -m venv .venv
source .venv/bin/activate        # On Windows: .venv\Scripts\activate
pip install ansible pre-commit
```

---

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com//AI-CQ-Pipeline.git
cd AI-CQ-Pipeline
```

### 2. Set up the GitHub Actions Workflows

Manually copy the workflow files from `pipeline/workflows/` into the `.github/workflows/` directory of the repository you want to analyze.

### 3. Deploy Infrastructure with Ansible

Navigate to the `/ansible` directory and follow the instructions in its `README.md`. This will configure the AWS infrastructure, Docker image, and GitHub repository secrets.


## Pre-commit Hooks 

To enable pre-commit hooks for local development:

```bash
pre-commit install
```

---

## License

This project is licensed under the [MIT License](LICENSE).
