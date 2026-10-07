"""Provider-agnostic extraction. OpenAI, Anthropic, or a fully offline mock."""

from __future__ import annotations

import json
import logging
import time
from typing import Callable, Protocol

import httpx
from pydantic import ValidationError

from doc_extractor.config import Settings
from doc_extractor.labeled import parse_coi, parse_invoice
from doc_extractor.logging_config import log_event
from doc_extractor.models import SchemaSpec, get_schema, load_json_schema
from doc_extractor.review import preliminary_judgement

logger = logging.getLogger("doc_extractor.llm")

SYSTEM_PROMPT = (
    "You extract structured fields from business documents. "
    "Return only JSON that matches the schema. "
    "Copy values that are printed. Do not guess a policy number, a total, or a date. "
    "If a value is missing, use null and explain it in review_reasons. "
    "confidence is your certainty from 0 to 1. "
    "Set needs_review to true when a required field is missing or the text is incomplete. "
    "Do not calculate expiry status, do not decide if a date is past due, "
    "and do not decide whether a reminder should be sent."
)


class ProviderError(RuntimeError):
    """The model call failed or returned something that is not JSON."""


class ExtractionFailed(RuntimeError):
    """Validation still failed after the configured retries."""


class LLMProvider(Protocol):
    name: str

    def extract(
        self,
        text: str,
        schema: SchemaSpec,
        *,
        filename: str = "",
        attempt_feedback: str = "",
    ) -> dict:
        ...


class MockProvider:
    """Offline stand-in.

    It reads labeled sample text. If that fails, it uses a canned JSON file
    generated with the sample PDFs. No network call is made.
    """

    name = "mock"

    def __init__(self, settings: Settings):
        self.settings = settings

    def extract(
        self,
        text: str,
        schema: SchemaSpec,
        *,
        filename: str = "",
        attempt_feedback: str = "",
    ) -> dict:
        del attempt_feedback
        parsed = parse_coi(text) if schema.name == "coi" else parse_invoice(text)
        if parsed.get(schema.title_field):
            log_event(logger, logging.INFO, "mock_parsed_labels", schema=schema.name, filename=filename)
            return preliminary_judgement(parsed, schema)
        canned = _load_canned(self.settings, text, filename, schema.name)
        if canned is not None:
            log_event(logger, logging.INFO, "mock_used_canned_response", schema=schema.name, filename=filename)
            return canned
        log_event(logger, logging.INFO, "mock_partial_parse", schema=schema.name, filename=filename)
        return preliminary_judgement(parsed, schema)


class OpenAIProvider:
    name = "openai"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        if not settings.openai_api_key:
            raise ProviderError("OPENAI_API_KEY is empty. Set it, or use LLM_PROVIDER=mock.")
        self.settings = settings
        self.client = client or httpx.Client(timeout=60)

    def extract(
        self,
        text: str,
        schema: SchemaSpec,
        *,
        filename: str = "",
        attempt_feedback: str = "",
    ) -> dict:
        schema_json = load_json_schema(schema.name)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(text, schema, filename, self.settings.text_char_limit)},
        ]
        if attempt_feedback:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "The previous response failed validation: "
                        f"{attempt_feedback}. Return corrected JSON only."
                    ),
                }
            )
        body = {
            "model": self.settings.openai_model,
            "temperature": 0,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": f"{schema.name}_extraction",
                    "strict": True,
                    "schema": schema_json,
                },
            },
        }
        response = self.client.post(
            f"{self.settings.openai_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
            json=body,
        )
        if response.status_code >= 400:
            raise ProviderError(f"OpenAI HTTP {response.status_code}: {response.text[:500]}")
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"Unexpected OpenAI response: {payload}") from exc
        return _parse_json_content(content)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        if not settings.anthropic_api_key:
            raise ProviderError("ANTHROPIC_API_KEY is empty. Set it, or use LLM_PROVIDER=mock.")
        self.settings = settings
        self.client = client or httpx.Client(timeout=60)

    def extract(
        self,
        text: str,
        schema: SchemaSpec,
        *,
        filename: str = "",
        attempt_feedback: str = "",
    ) -> dict:
        schema_json = load_json_schema(schema.name)
        user_content = _user_prompt(text, schema, filename, self.settings.text_char_limit)
        if attempt_feedback:
            user_content += (
                "\n\nThe previous response failed validation: "
                f"{attempt_feedback}. Call the tool again with corrected values."
            )
        body = {
            "model": self.settings.anthropic_model,
            "max_tokens": 2000,
            "temperature": 0,
            "system": SYSTEM_PROMPT,
            "tools": [
                {
                    "name": "record_extraction",
                    "description": f"Record structured fields for a {schema.title}.",
                    "input_schema": schema_json,
                }
            ],
            "tool_choice": {"type": "tool", "name": "record_extraction"},
            "messages": [{"role": "user", "content": user_content}],
        }
        response = self.client.post(
            f"{self.settings.anthropic_base_url.rstrip('/')}/messages",
            headers={
                "x-api-key": self.settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
        )
        if response.status_code >= 400:
            raise ProviderError(f"Anthropic HTTP {response.status_code}: {response.text[:500]}")
        payload = response.json()
        for block in payload.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == "record_extraction":
                tool_input = block.get("input")
                if isinstance(tool_input, dict):
                    return tool_input
                raise ProviderError("Anthropic tool input was not an object.")
        text_blocks = [block.get("text", "") for block in payload.get("content", []) if block.get("type") == "text"]
        if text_blocks:
            return _parse_json_content("\n".join(text_blocks))
        raise ProviderError(f"Unexpected Anthropic response: {payload}")


def build_provider(settings: Settings) -> LLMProvider:
    name = settings.llm_provider.lower().strip()
    if name == "mock":
        return MockProvider(settings)
    if name == "openai":
        return OpenAIProvider(settings)
    if name == "anthropic":
        return AnthropicProvider(settings)
    raise ProviderError(
        f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Use mock, openai, or anthropic."
    )


def extract_with_retries(
    provider: LLMProvider,
    text: str,
    schema: SchemaSpec,
    *,
    filename: str = "",
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
):
    feedback = ""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            raw = provider.extract(text, schema, filename=filename, attempt_feedback=feedback)
            if not isinstance(raw, dict):
                raise ProviderError("The model did not return a JSON object.")
            return schema.model.model_validate(raw)
        except (ProviderError, ValidationError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            feedback = str(exc)
            log_event(
                logger,
                logging.WARNING,
                "extraction_attempt_failed",
                attempt=attempt,
                attempts=attempts,
                provider=provider.name,
                filename=filename,
                error=feedback[:500],
            )
            if attempt < attempts:
                sleep(min(8.0, 0.4 * (2 ** (attempt - 1))))
    raise ExtractionFailed(f"Extraction failed after {attempts} attempts: {last_error}") from last_error


def _user_prompt(text: str, schema: SchemaSpec, filename: str, limit: int) -> str:
    clipped = text[:limit]
    return (
        f"Document type: {schema.title}\n"
        f"Schema name: {schema.name}\n"
        f"Filename: {filename or 'unknown'}\n\n"
        f"Document text:\n{clipped}"
    )


def _parse_json_content(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ProviderError("JSON response was not an object.")
    return parsed


def _load_canned(settings: Settings, text: str, filename: str, schema_name: str) -> dict | None:
    folder = settings.samples_dir / "canned"
    if not folder.exists():
        return None
    entries = []
    for path in sorted(folder.glob("*.json")):
        try:
            entries.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    wanted_name = filename.lower()
    for entry in entries:
        if entry.get("schema") != schema_name:
            continue
        if str(entry.get("filename", "")).lower() == wanted_name and entry.get("payload"):
            return entry["payload"]
    lowered = text.lower()
    for entry in entries:
        if entry.get("schema") != schema_name:
            continue
        needle = str(entry.get("needle") or "").lower()
        if needle and needle in lowered and entry.get("payload"):
            return entry["payload"]
    return None


def schema_from_hint(hint: str | None, filename: str, text: str, parent_name: str | None, default: str) -> SchemaSpec:
    if hint and hint != "auto":
        return get_schema(hint)
    if parent_name in {"coi", "invoice"}:
        return get_schema(parent_name)
    lower = filename.lower()
    if "invoice" in lower:
        return get_schema("invoice")
    if "coi" in lower or "certificate" in lower:
        return get_schema("coi")
    head = text[:2000].lower()
    if "invoice number" in head:
        return get_schema("invoice")
    if "named insured" in head or "certificate of insurance" in head:
        return get_schema("coi")
    return get_schema(default)
