# AI-CQ-Pipeline: Automated Software Quality Analysis and Repair in CI/CD

A pipeline-driven system that integrates **static code analysis**, **LLM-based refactoring**, and **continuous verification** into a modern CI/CD workflow. Triggered by pull requests, it automatically analyzes code quality, invokes an LLM to generate refactors, and feeds results back to GitHub.

## Overview

CI/CD pipelines automate build, test, and deployment but they do not inherently ensure software quality. This system addresses that gap by targeting key quality dimensions:

- **Maintainability Index**
- **Cyclomatic Complexity**
- **Code Smells**

Our approach is cloud-based, extensible, and designed for industrial CI/CD settings. It integrates static analysis tools with LLM-based repair, overcoming the limitations of fragmented tooling and lack of software quality awareness in LLMs.

---

## Requirements

- Python 3.10+
- AWS account (Fargate, ECR, and related services)
- GitHub repository with Actions enabled
- Ansible 2.12+

Install Python dependencies:

```bash
python -m venv venv
source venv/bin/activate        # On Windows: venv\Scripts\activate
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

Copy the workflow files to your target repository:

```bash
cp pipeline/workflows/*.yml /.github/workflows/
```

### 3. Configure AWS Environment Variables

Edit the configuration file at `/pipeline/fargate/src/variables.py` and set the value to match your AWS environment:

| Variable | Default |
| :---: | :---: |
| `PREFIX` | `ai-cq-pipeline` |
| `AWS_REGION` | `eu-central-1` | 

> **Note:** Make sure `AWS_REGION` here matches the region in `pipeline/workflows/start-pipeline-run.yml`.

### 4. Configure GitHub Secrets

In your GitHub repository, go to **Settings → Secrets and variables → Actions** and add the following secrets. The workflow in `pipeline/workflows/start-pipeline-run.yml` already references them automatically

| Secret | Description |
| :---: | :---: |
| `AWS_ROLE_ARN` | IAM role ARN for OIDC authentication |
| `ECS_CLUSTER` | ECS Fargate cluster name |
| `ECS_TASK_DEFINITION` | Fargate task definition name |
| `SUBNET_IDS` | JSON array of subnet IDs, e.g. `["subnet-abc","subnet-def"]` |
| `SECURITY_GROUP_IDS` | JSON array of security group IDs |
| `CONTAINER_NAME` | Name of the container in the task definition |

### 5. Deploy Infrastructure with Ansible

Navigate to the `/ansible` directory and follow the instructions in its `README.md`:

```bash
cd ansible
# Follow ansible/README.md
```

---

## Pre-commit Hooks (Development)

To enable pre-commit hooks for local development:

```bash
pre-commit install
```

---

## License

This project is licensed under the [MIT License](LICENSE).
