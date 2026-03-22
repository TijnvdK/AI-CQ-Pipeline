# Getting Started

1. Clone the repository:

```bash
git clone
cd AI-CQ-Pipeline
```
2. Copy the GitHub Action Workflows under `/pipeline/workflows` to your repository's `.github/workflows` directory.
3. Set the variables under `/pipeline/fargate/src/variables.py` to match your AWS environment. Use the same values as in the following step.
4. Navigate to `/ansible` and follow the steps in the `README.md` in that directory.

If you want to setup the pre-commit hooks for development:

1. Install Python tooling

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install ansible pre-commit
```

2. Install pre-commit hooks

```bash
pre-commit install
```
