import json

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.schemas import Preferences, Reference, Result, Source, TurnPlan, Usage
from app.sessions import Sessions


def test_unrestricted_request_does_not_default_to_vegetarian():
    assert Preferences(city="Berlin").vegetarian is False


def test_sessions_keep_context_and_expire():
    store = Sessions()
    session = store.get(None)
    session.remember("user", "Berlin lunch")
    assert store.get(session.id).history[0]["content"] == "Berlin lunch"
    session.updated -= 3601
    assert store.get(session.id) is None


def test_followup_answers_from_previous_evidence_without_web_search(monkeypatch):
    monkeypatch.setattr(
        "app.main.get_settings",
        lambda: Settings(_env_file=None, gemini_api_key="test", tavily_api_key="test"),
    )
    store = Sessions()
    session = store.get(None)
    session.preferences = Preferences(city="Barcelona", budget=20, currency="EUR")
    session.result = Result(
        preferences=session.preferences,
        recommendations=[],
        excluded=[],
        sources=[],
        usage=Usage(),
        warnings=[],
    )
    session.sources = {
        "s1": Source(
            id="s1",
            url="https://restaurant.example/menu",
            title="Menu",
            text="Bowl 14 €",
            coverage="extracted_page",
        )
    }
    monkeypatch.setattr("app.main.sessions", store)

    async def plan(llm, instruction, payload, schema):
        assert payload["previous_preferences"]["city"] == "Barcelona"
        return TurnPlan(
            preferences=session.preferences,
            action="answer",
            reply="The bowl is €14 on the menu.",
            refs=[Reference(source_id="s1", quote="Bowl 14 €")],
        )

    async def no_search(*args, **kwargs):
        raise AssertionError("Existing evidence should be reused")

    monkeypatch.setattr("app.agent.Gemini.structured", plan)
    monkeypatch.setattr("app.agent.Web.search", no_search)
    with TestClient(app) as client:
        response = client.post(
            "/api/recommendations",
            json={"message": "What does the bowl cost?", "session_id": session.id},
        )
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "answer"
    assert events[-1]["data"]["refs"][0]["quote"] == "Bowl 14 €"
    assert session.history[-2]["content"] == "What does the bowl cost?"


def test_expired_session_returns_clear_error(monkeypatch):
    monkeypatch.setattr(
        "app.main.get_settings",
        lambda: Settings(_env_file=None, gemini_api_key="test", tavily_api_key="test"),
    )
    monkeypatch.setattr("app.main.sessions", Sessions())
    with TestClient(app) as client:
        response = client.post(
            "/api/recommendations", json={"message": "What about lunch?", "session_id": "f" * 32}
        )
    assert response.json()["type"] == "error"
    assert "expired" in response.json()["message"]
