# Getting Started - Deployment Guide

1. Copy the GitHub Action Workflows under `/pipeline/workflows` to your repository's `.github/workflows` directory.
2. Set the variables under `/pipeline/fargate/src/variables.py` to match your AWS environment. Use the same values as in the following step.
3. Navigate to `/ansible` and follow the step in the `README.md` in that directory.

# Getting Started - Developer Guide

1. Clone the repository:

```bash
git clone
cd AI-CQ-Pipeline
```

2. Install Python tooling

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install ansible pre-commit
```

3. Install pre-commit hooks

```bash
pre-commit install
```
