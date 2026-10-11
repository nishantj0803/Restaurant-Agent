from datetime import date, datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Reference(Model):
    source_id: str
    quote: str = Field(min_length=3, max_length=1200)


class Request(Model):
    message: str = Field(min_length=1, max_length=4000)
    timezone: str = "Europe/Madrid"
    clarification_answers: list[str] = Field(default_factory=list, max_length=5)
    session_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Use a valid IANA timezone") from None
        return value

    @field_validator("clarification_answers")
    @classmethod
    def bounded_answers(cls, values: list[str]) -> list[str]:
        if any(len(value) > 1000 for value in values):
            raise ValueError("Clarification answers must be at most 1000 characters")
        return values


class Preferences(Model):
    city: str | None = None
    country: str | None = None
    meal: Literal["breakfast", "lunch", "dinner", "any"] = "any"
    visit_date: date | None = None
    budget: float | None = Field(default=None, gt=0, le=10000)
    currency: str | None = None
    budget_operator: Literal["lt", "lte"] = "lte"
    vegetarian: bool = False
    excluded_ingredients: list[str] = Field(default_factory=list, max_length=8)
    location_preference: str = ""
    review_concerns: list[str] = Field(default_factory=list, max_length=6)
    search_queries: list[str] = Field(default_factory=list, max_length=2)
    assumptions: list[str] = Field(default_factory=list)
    clarification: str | None = None


class TurnPlan(Model):
    preferences: Preferences
    action: Literal["research", "answer"] = "research"
    reply: str = ""
    refs: list[Reference] = Field(default_factory=list)


class Source(Model):
    id: str
    url: str
    title: str
    text: str = Field(exclude=True)
    coverage: Literal["search_excerpt", "extracted_page", "pdf"]
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_date: str | None = None


class Candidate(Model):
    name: str
    website: str
    address: str = ""
    reason: str
    discovery_refs: list[Reference] = Field(default_factory=list)


class Shortlist(Model):
    candidates: list[Candidate] = Field(max_length=4)


class DietaryFact(Model):
    ingredient: str
    status: Literal["absent", "present", "unknown"]
    refs: list[Reference] = Field(default_factory=list)


class Dish(Model):
    original_name: str
    english_name: str
    description: str
    ingredients: list[str] = Field(default_factory=list)
    ingredient_refs: list[Reference] = Field(default_factory=list)
    price: float | None = Field(default=None, ge=0)
    currency: str | None = None
    price_kind: Literal["exact", "from", "unknown"] = "unknown"
    menu_category: Literal["regular", "set_menu", "special", "unknown"] = "unknown"
    item_type: Literal["food", "drink", "unknown"] = "food"
    meal_availability: Literal["breakfast", "lunch", "dinner", "any", "unknown"] = "unknown"
    meal_refs: list[Reference] = Field(default_factory=list)
    vegetarian: Literal["yes", "no", "unknown"] = "unknown"
    vegan: Literal["yes", "no", "unknown"] = "unknown"
    dietary_refs: list[Reference] = Field(default_factory=list)
    exclusions: list[DietaryFact] = Field(default_factory=list)
    menu_refs: list[Reference] = Field(default_factory=list)
    price_refs: list[Reference] = Field(default_factory=list)
    status: Literal["supported", "confirmation", "excluded"] = "confirmation"
    reasons: list[str] = Field(default_factory=list)


class Review(Model):
    polarity: Literal["positive", "negative", "mixed"]
    aspect: Literal["food", "service", "dietary", "value", "other"]
    summary: str
    source_type: Literal["customer_review", "editorial", "testimonial", "unknown"]
    review_date: str | None = None
    refs: list[Reference] = Field(min_length=1)


class Finding(Model):
    official_website: str | None = None
    address: str = ""
    location_summary: str = ""
    location_refs: list[Reference] = Field(default_factory=list)
    availability: Literal["compatible", "conflict", "unknown"] = "unknown"
    availability_summary: str = ""
    availability_refs: list[Reference] = Field(default_factory=list)
    menu_url: str | None = None
    dishes: list[Dish] = Field(default_factory=list, max_length=8)
    reviews: list[Review] = Field(default_factory=list, max_length=8)
    gaps: list[str] = Field(default_factory=list)


class Recommendation(Model):
    name: str
    website: str
    menu_url: str | None
    address: str
    location_summary: str
    location_refs: list[Reference]
    status: Literal["supported", "confirmation", "excluded"]
    explanation: str
    dishes: list[Dish]
    reviews: list[Review]
    availability_summary: str
    availability_refs: list[Reference]
    gaps: list[str]


class Usage(Model):
    searches: int = 0
    documents: int = 0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_seconds: float = 0


class Result(Model):
    preferences: Preferences
    recommendations: list[Recommendation]
    excluded: list[Recommendation]
    sources: list[Source]
    usage: Usage
    warnings: list[str]


class Event(Model):
    type: str
    stage: str
    message: str
    data: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
