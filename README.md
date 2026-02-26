## Getting Started

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

4. Copy workflow file: "run-correctness-tests" to where you want to run the pipeline
