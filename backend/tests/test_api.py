import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.llm import Gemini, ProviderError, generation_schema
from app.main import app
from app.schemas import Finding, Preferences, TurnPlan, Usage


def test_generation_schema_omits_array_bounds_but_local_validation_keeps_them():
    provider_schema = generation_schema(Finding)
    local_schema = Finding.model_json_schema()
    assert "maxItems" not in json.dumps(provider_schema)
    assert "minItems" not in json.dumps(provider_schema)
    assert local_schema["properties"]["dishes"]["maxItems"] == 8
    assert local_schema["$defs"]["Review"]["properties"]["refs"]["minItems"] == 1


@pytest.fixture
def client():
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def test_missing_configuration_is_explicit(client, monkeypatch):
    monkeypatch.setattr(
        "app.main.get_settings",
        lambda: Settings(_env_file=None, gemini_api_key="", tavily_api_key=""),
    )
    response = client.post("/api/recommendations", json={"message": "Barcelona vegetarian lunch"})
    event = response.json()
    assert event["type"] == "error"
    assert "GEMINI_API_KEY" in event["message"]


def test_invalid_timezone_rejected(client):
    response = client.post(
        "/api/recommendations", json={"message": "Berlin lunch", "timezone": "not-a-timezone"}
    )
    assert response.status_code == 422


def test_clarification_happens_before_web_search(client, monkeypatch):
    monkeypatch.setattr(
        "app.main.get_settings",
        lambda: Settings(_env_file=None, gemini_api_key="test", tavily_api_key="test"),
    )

    async def parse(*args, **kwargs):
        return TurnPlan(
            preferences=Preferences(country="Germany", meal="lunch", budget=20, currency="EUR")
        )

    async def search(*args, **kwargs):
        pytest.fail("No search should run before a city is supplied")

    monkeypatch.setattr("app.agent.Gemini.structured", parse)
    monkeypatch.setattr("app.agent.Web.search", search)
    response = client.post(
        "/api/recommendations", json={"message": "Germany tomorrow, vegetarian lunch under €20"}
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "clarification"
    assert "city" in events[-1]["message"]


async def test_gemini_payload_and_structured_parsing():
    def respond(request):
        body = json.loads(request.content)
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert "responseJsonSchema" in body["generationConfig"]
        assert request.headers["x-goog-api-key"] == "test"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": json.dumps({"city": "Barcelona"})}]}}
                ],
                "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 10},
            },
        )

    usage = Usage()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        gemini = Gemini(client, Settings(_env_file=None, gemini_api_key="test"), usage)
        result = await gemini.structured("Extract", {"message": "Barcelona"}, Preferences)
    assert result.city == "Barcelona"
    assert usage.input_tokens == 20
    assert usage.output_tokens == 10


async def test_gemini_authentication_error_does_not_expose_key():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(403, json={"error": "secret"}))
    ) as client:
        gemini = Gemini(client, Settings(_env_file=None, gemini_api_key="test-secret"), Usage())
        with pytest.raises(ProviderError, match="access was denied") as error:
            await gemini.structured("Extract", {}, Preferences)
    assert "test-secret" not in str(error.value)
