import json

import httpx
import pytest

from doc_extractor.config import load_settings
from doc_extractor.llm import (
    AnthropicProvider,
    ExtractionFailed,
    OpenAIProvider,
    ProviderError,
    extract_with_retries,
)
from doc_extractor.models import get_schema


COI = {
    "company_name": "Northwind Scaffolding LLC",
    "policy_number": "GL-88421-NW",
    "insurer": "Pinnacle Mutual Insurance",
    "coverage_types": ["General Liability"],
    "limits": [{"coverage_type": "General Liability", "limit": "$1,000,000"}],
    "effective_date": "2026-01-01",
    "expiry_date": "2026-10-24",
    "confidence": 0.91,
    "needs_review": False,
    "review_reasons": [],
}


def test_openai_sends_json_schema(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(COI)}}]})

    settings = load_settings(llm_provider="openai", openai_api_key="test-key")
    provider = OpenAIProvider(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    parsed = provider.extract("Named Insured: Northwind", get_schema("coi"), filename="coi.pdf")
    assert parsed["policy_number"] == "GL-88421-NW"
    assert seen["auth"] == "Bearer test-key"
    response_format = seen["body"]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert "expiry_status" not in response_format["json_schema"]["schema"]["properties"]
    assert seen["body"]["temperature"] == 0


def test_anthropic_reads_tool_input():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        assert body["tool_choice"]["name"] == "record_extraction"
        assert "expiry_status" not in body["tools"][0]["input_schema"]["properties"]
        return httpx.Response(
            200,
            json={"content": [{"type": "tool_use", "name": "record_extraction", "input": COI}]},
        )

    settings = load_settings(llm_provider="anthropic", anthropic_api_key="test-key")
    provider = AnthropicProvider(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    parsed = provider.extract("certificate text", get_schema("coi"))
    assert parsed["company_name"] == "Northwind Scaffolding LLC"


def test_retries_then_succeeds():
    class Flaky:
        name = "flaky"

        def __init__(self):
            self.calls = 0

        def extract(self, text, schema, *, filename="", attempt_feedback=""):
            self.calls += 1
            if self.calls < 3:
                raise ProviderError("temporary")
            return COI

    provider = Flaky()
    model = extract_with_retries(
        provider,
        "text",
        get_schema("coi"),
        attempts=3,
        sleep=lambda _seconds: None,
    )
    assert provider.calls == 3
    assert model.policy_number == "GL-88421-NW"


def test_retries_exhausted():
    class AlwaysBad:
        name = "bad"

        def extract(self, text, schema, *, filename="", attempt_feedback=""):
            return {"company_name": 12}

    with pytest.raises(ExtractionFailed):
        extract_with_retries(
            AlwaysBad(),
            "text",
            get_schema("coi"),
            attempts=2,
            sleep=lambda _seconds: None,
        )


def test_openai_requires_a_key():
    settings = load_settings(llm_provider="openai", openai_api_key="")
    with pytest.raises(Exception):
        OpenAIProvider(settings)
