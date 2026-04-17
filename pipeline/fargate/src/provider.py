import os
import re
from abc import ABC, abstractmethod
from logging import getLogger
from typing import Optional, Type

from boto3 import client as boto3_client
from variables import PREFIX

ssm = boto3_client("ssm")
logger = getLogger(__name__)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class LLMProvider(ABC):
    @abstractmethod
    def complete(self, original_code: str) -> Optional[str]:
        """Send code to the model and return the refactored code string. Return None on failure."""
        raise NotImplementedError

    def complete_with_prompt(self, user_prompt: str) -> Optional[str]:
        """
        Send a custom user prompt (with system prompt) and return extracted code.
        Default falls back to complete() for backward compatibility.
        Subclasses should override for proper handling.
        """
        return self.complete(user_prompt)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are an expert software engineer. "
    "Return ONLY the refactored Python code wrapped in triple backticks with 'python' language identifier. "
    "Format your response exactly like this:\n\n"
    "```python\n"
    "# your refactored code here\n"
    "```\n\n"
    "You MUST preserve the original function's name, signature, and all decorators exactly as-is. "
    "You may extract logic into additional helper functions and call them from within the original function, "
    "but the original function's name, parameters, and decorators must remain unchanged. "
    "Any helper functions you create MUST be a nested function of the original function. "
    "Do not include any explanation, comments, or additional text outside the code block."
)


def _user_prompt(original_code: str) -> str:
    return (
        "With no explanation refactor the Python code to improve its quality:"
        f"\n\n```python\n{original_code}\n```"
    )


def _build_messages_openai(original_code: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _user_prompt(original_code)},
    ]


def _build_messages_openai_custom(user_prompt: str) -> list[dict[str, str]]:
    """Build messages with a custom user prompt (for targeted refactoring)."""
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _extract_python_code_block(text: Optional[str]) -> Optional[str]:
    if not text:
        return None

    match = re.search(r"```python\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    match = re.search(r"```\s*(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    return text.strip()


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class OpenAIProvider(LLMProvider):
    """Generic OpenAI provider for GPT models."""

    def __init__(self, api_key: str, model: str):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model = model

    def complete(self, original_code: str) -> Optional[str]:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=_build_messages_openai(original_code),
                max_completion_tokens=32768,
            )
            content = resp.choices[0].message.content
            return _extract_python_code_block(content)
        except Exception as e:
            logger.exception("OpenAIProvider (%s) error: %s", self.model, e)
            return None

    def complete_with_prompt(self, user_prompt: str) -> Optional[str]:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=_build_messages_openai_custom(user_prompt),
                max_completion_tokens=32768,
            )
            content = resp.choices[0].message.content
            return _extract_python_code_block(content)
        except Exception as e:
            logger.exception("OpenAIProvider (%s) complete_with_prompt error: %s", self.model, e)
            return None


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def complete(self, original_code: str) -> Optional[str]:
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=16000,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": _user_prompt(original_code)}],
            )
            text = "".join(
                block.text for block in resp.content if getattr(block, "type", None) == "text"
            )
            return _extract_python_code_block(text)
        except Exception as e:
            logger.exception("ClaudeProvider (%s) error: %s", self.model, e)
            return None

    def complete_with_prompt(self, user_prompt: str) -> Optional[str]:
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=16000,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = "".join(
                block.text for block in resp.content if getattr(block, "type", None) == "text"
            )
            return _extract_python_code_block(text)
        except Exception as e:
            logger.exception("ClaudeProvider (%s) complete_with_prompt error: %s", self.model, e)
            return None


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.model = model

    def complete(self, original_code: str) -> Optional[str]:
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=_user_prompt(original_code),
                config={
                    "system_instruction": _SYSTEM_PROMPT,
                },
            )
            return _extract_python_code_block(getattr(resp, "text", None))
        except Exception as e:
            logger.exception("GeminiProvider (%s) error: %s", self.model, e)
            return None

    def complete_with_prompt(self, user_prompt: str) -> Optional[str]:
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config={
                    "system_instruction": _SYSTEM_PROMPT,
                },
            )
            return _extract_python_code_block(getattr(resp, "text", None))
        except Exception as e:
            logger.exception("GeminiProvider (%s) complete_with_prompt error: %s", self.model, e)
            return None


class DeepSeekProvider(LLMProvider):
    """DeepSeek uses OpenAI-compatible SDK with a different base_url."""

    def __init__(self, api_key: str, model: str):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        self.model = model

    def complete(self, original_code: str) -> Optional[str]:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=_build_messages_openai(original_code),
                max_tokens=32768,
            )
            content = resp.choices[0].message.content
            return _extract_python_code_block(content)
        except Exception as e:
            logger.exception("DeepSeekProvider (%s) error: %s", self.model, e)
            return None

    def complete_with_prompt(self, user_prompt: str) -> Optional[str]:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=_build_messages_openai_custom(user_prompt),
                max_tokens=32768,
            )
            content = resp.choices[0].message.content
            return _extract_python_code_block(content)
        except Exception as e:
            logger.exception("DeepSeekProvider (%s) complete_with_prompt error: %s", self.model, e)
            return None


# ---------------------------------------------------------------------------
# Model config
# ---------------------------------------------------------------------------

ProviderConfig = tuple[Type[LLMProvider], str, str]

_MODEL_CONFIG: dict[str, ProviderConfig] = {
    # OpenAI
    "gpt54nano": (OpenAIProvider, "gpt-5.4-nano", "openai-api-key"),
    "gpt54mini": (OpenAIProvider, "gpt-5.4-mini", "openai-api-key"),
    "gpt54": (OpenAIProvider, "gpt-5.4", "openai-api-key"),

    # Anthropic
    "claude": (ClaudeProvider, "claude-sonnet-4-6", "claude-api-key"),

    # Google
    "gemini": (GeminiProvider, "gemini-3-flash-preview", "gemini-api-key"),

    # DeepSeek
    "deepseek": (DeepSeekProvider, "deepseek-reasoner", "deepseek-api-key"),
}


def _get_api_key(ssm_key_suffix: str) -> str:
    ssm_key = f"/{PREFIX}/{ssm_key_suffix}"
    try:
        resp = ssm.get_parameter(Name=ssm_key, WithDecryption=True)
        return resp["Parameter"]["Value"]
    except Exception as e:
        logger.exception("Error retrieving API key from SSM (%s): %s", ssm_key, e)
        raise


def get_provider() -> LLMProvider:
    """
    Read provider config from environment variable LLM_PROVIDER and return the provider instance.

    Valid values (case-insensitive):
        gpt54nano | gpt54mini | gpt54 | claude | gemini | deepseek

    Optional:
        LLM_MODEL can override the default model name.
    """
    provider_name = "gpt54nano"

    if provider_name not in _MODEL_CONFIG:
        valid = ", ".join(sorted(_MODEL_CONFIG.keys()))
        raise ValueError(f"Unknown LLM_PROVIDER: {provider_name!r}. Valid options: {valid}")

    provider_cls, default_model, ssm_key_suffix = _MODEL_CONFIG[provider_name]
    model = os.environ.get("LLM_MODEL", default_model)
    api_key = _get_api_key(ssm_key_suffix)

    logger.info("Using provider '%s' with model '%s'.", provider_name, model)
    return provider_cls(api_key, model)
