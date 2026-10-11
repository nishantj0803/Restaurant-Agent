import json
from datetime import date

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.schemas import (
    Candidate,
    Dish,
    Finding,
    Preferences,
    Reference,
    Review,
    Shortlist,
    TurnPlan,
)


def test_research_stream_with_sourced_menu_and_both_review_sides(monkeypatch):
    text = "Sample Restaurant Barcelona. Ensalada vegana 15 €. Great food and friendly staff. Service was slow at lunch. Open lunch 12:00 to 16:00 on 2026-10-11."
    sources = {}

    async def search(web, query, max_results=5):
        web.usage.searches += 1
        source = web.add_source(
            "https://sample.example/menu", "Sample menu", text, "search_excerpt"
        )
        sources[source.id] = source
        return [source]

    async def read(web, urls):
        web.usage.documents += 1
        source = web.add_source(
            "https://sample.example/menu", "Sample menu", text, "extracted_page"
        )
        sources[source.id] = source
        return [source]

    async def structured(llm, instruction, payload, schema):
        llm.usage.llm_calls += 1
        if schema is TurnPlan:
            return TurnPlan(
                preferences=Preferences(
                    city="Barcelona",
                    meal="lunch",
                    visit_date=date(2026, 10, 11),
                    budget=20,
                    currency="EUR",
                    budget_operator="lt",
                    excluded_ingredients=["egg"],
                    vegetarian=True,
                )
            )
        first_id = next(iter(sources))

        def ref(quote):
            return Reference(source_id=first_id, quote=quote)

        if schema is Shortlist:
            return Shortlist(
                candidates=[
                    Candidate(
                        name="Sample Restaurant",
                        website="https://sample.example/menu",
                        reason="Relevant published menu",
                        discovery_refs=[ref("Sample Restaurant Barcelona")],
                    )
                ]
            )
        return Finding(
            menu_url="https://sample.example/menu",
            availability="compatible",
            availability_summary="Published lunch hours cover the example visit.",
            availability_refs=[ref("Open lunch 12:00 to 16:00 on 2026-10-11")],
            dishes=[
                Dish(
                    original_name="Ensalada",
                    english_name="Salad",
                    description="Vegan salad",
                    price=15,
                    currency="EUR",
                    price_kind="exact",
                    menu_category="regular",
                    vegetarian="yes",
                    vegan="yes",
                    menu_refs=[ref("Ensalada vegana 15 €")],
                    dietary_refs=[ref("Ensalada vegana 15 €")],
                    price_refs=[ref("Ensalada vegana 15 €")],
                )
            ],
            reviews=[
                Review(
                    polarity="positive",
                    aspect="food",
                    summary="Good food and friendly staff",
                    source_type="customer_review",
                    refs=[ref("Great food and friendly staff")],
                ),
                Review(
                    polarity="negative",
                    aspect="service",
                    summary="Slow lunch service",
                    source_type="customer_review",
                    refs=[ref("Service was slow at lunch")],
                ),
            ],
        )

    monkeypatch.setattr(
        "app.main.get_settings",
        lambda: Settings(_env_file=None, gemini_api_key="test", tavily_api_key="test"),
    )
    monkeypatch.setattr("app.agent.Web.search", search)
    monkeypatch.setattr("app.agent.Web.read", read)
    monkeypatch.setattr("app.agent.Gemini.structured", structured)
    with TestClient(app) as client:
        response = client.post(
            "/api/recommendations",
            json={"message": "Barcelona vegetarian egg-free lunch under €20"},
        )
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "result"
    result = events[-1]["data"]["result"]
    recommendation = result["recommendations"][0]
    assert recommendation["status"] == "supported"
    assert recommendation["dishes"][0]["price"] == 15
    assert {review["polarity"] for review in recommendation["reviews"]} == {"positive", "negative"}
    assert all("text" not in source for source in result["sources"])
    assert {event["type"] for event in events} >= {
        "search",
        "candidate_found",
        "source_read",
        "evidence_found",
        "result",
    }
