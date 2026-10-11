import asyncio
import time
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx

from . import prompts
from .config import Settings
from .eligibility import rank_key, recommendation, valid_refs, validate_finding
from .llm import Gemini, ProviderError
from .menu import menu_blocks
from .schemas import (
    Candidate,
    Event,
    Finding,
    Recommendation,
    Request,
    Result,
    Shortlist,
    Source,
    TurnPlan,
    Usage,
)
from .sessions import Session
from .web import Web, normalize_url


class Agent:
    def __init__(self, settings: Settings, request: Request, emit, session: Session | None = None):
        self.settings = settings
        self.request = request
        self.emit = emit
        self.usage = Usage()
        self.preferences = None
        self.recommendations: list[Recommendation] = []
        self.warnings: list[str] = []
        self.started = time.monotonic()
        self.followups = 0
        self.emitted_sources = set()
        self.session = session or Session()

    async def event(self, kind: str, stage: str, message: str, **data):
        await self.emit(Event(type=kind, stage=stage, message=message, data=data))

    @staticmethod
    def source_payload(sources: list[Source]) -> list[dict]:
        return [
            {**source.model_dump(mode="json"), "text": source.text}
            for source in dict((source.id, source) for source in sources).values()
        ]

    async def record_sources(self, sources: list[Source], stage: str):
        for source in sources:
            if source.id in self.emitted_sources:
                continue
            self.emitted_sources.add(source.id)
            await self.event(
                "source_read", stage, source.title, source=source.model_dump(mode="json")
            )

    async def run(self):
        async with httpx.AsyncClient(headers={"User-Agent": "Tablefind/0.1"}) as client:
            self.web = Web(client, self.settings, self.usage)
            self.llm = Gemini(client, self.settings, self.usage)
            await self.event(
                "stage_started", "preferences", "Understanding your trip and dietary preferences"
            )
            local_date = datetime.now(ZoneInfo(self.request.timezone)).date()
            plan = await self.llm.structured(
                prompts.PARSE,
                {
                    "request": self.request.model_dump(),
                    "local_date": str(local_date),
                    "history": self.session.history,
                    "previous_preferences": self.session.preferences.model_dump(mode="json")
                    if self.session.preferences
                    else None,
                    "previous_result": self.session.result.model_dump(mode="json")
                    if self.session.result
                    else None,
                },
                TurnPlan,
            )
            self.session.remember("user", self.request.message)
            preferences = plan.preferences
            if plan.action == "answer":
                refs = valid_refs(plan.refs, self.session.sources)
                if self.session.result and plan.refs and not refs:
                    plan.reply = "I couldn't verify that from the sources we have. Ask me to search again for more detail."
                self.session.remember("assistant", plan.reply)
                await self.event(
                    "answer",
                    "complete",
                    plan.reply,
                    refs=[ref.model_dump() for ref in refs],
                    sources=[
                        source.model_dump(mode="json") for source in self.session.sources.values()
                    ],
                )
                return
            if not preferences.city or not preferences.city.strip():
                preferences.clarification = "Which city will you be visiting?"
            elif preferences.budget is not None and not preferences.currency:
                preferences.clarification = "Which currency is your meal budget in?"
            if preferences.clarification:
                self.session.preferences = preferences
                self.session.remember("assistant", preferences.clarification)
                await self.event("clarification", "preferences", preferences.clarification)
                return
            if preferences.currency:
                preferences.currency = preferences.currency.upper()
            if preferences.budget is not None:
                preferences.assumptions.append(
                    "Budget covers one main or breakfast item per person, excluding drinks, extras, and unlisted charges."
                )
            if preferences.vegetarian or preferences.excluded_ingredients:
                preferences.assumptions.append(
                    "Published ingredients do not establish allergy or cross-contact safety."
                )
            preferences.assumptions = list(dict.fromkeys(preferences.assumptions))
            self.preferences = preferences
            await self.event(
                "preferences",
                "preferences",
                "Preferences ready",
                preferences=preferences.model_dump(mode="json"),
            )
            await self.event(
                "stage_started", "discovery", f"Searching for restaurants in {preferences.city}"
            )
            queries = preferences.search_queries[:2] or [
                f"{preferences.city} {'vegetarian' if preferences.vegetarian else ''} {preferences.meal} restaurant menu {preferences.location_preference}"
            ]
            discovered = []
            for query in queries:
                await self.event("search", "discovery", query)
                discovered.extend(await self.web.search(query, 6))
            await self.record_sources(discovered, "discovery")
            if not discovered:
                await self.event(
                    "warning", "discovery", "No usable restaurant sources were returned."
                )
                await self.finish()
                return
            await self.event(
                "stage_started", "shortlist", "Shortlisting restaurants from the retrieved sources"
            )
            shortlist = await self.llm.structured(
                prompts.SHORTLIST,
                {
                    "preferences": preferences.model_dump(mode="json"),
                    "sources": self.source_payload(discovered),
                },
                Shortlist,
            )
            candidates = []
            seen = set()
            for candidate in shortlist.candidates:
                candidate.discovery_refs = valid_refs(candidate.discovery_refs, self.web.sources)
                key = normalize_url(candidate.website)
                if (
                    not candidate.discovery_refs
                    or not self.web.known_url(candidate.website)
                    or key in seen
                ):
                    continue
                seen.add(key)
                candidates.append(candidate)
                await self.event(
                    "candidate_found",
                    "shortlist",
                    candidate.name,
                    candidate=candidate.model_dump(mode="json"),
                )
            await self.event(
                "stage_started",
                "research",
                f"Reading menus and contextual reviews for {len(candidates)} restaurants",
            )
            semaphore = asyncio.Semaphore(2)

            async def research(candidate):
                async with semaphore:
                    try:
                        await self.research(candidate)
                    except ProviderError as exc:
                        message = f"{candidate.name}: {exc}"
                        self.warnings.append(message)
                        await self.event("warning", "research", message)

            await asyncio.gather(*(research(candidate) for candidate in candidates))
            await self.finish()

    async def research(self, candidate: Candidate):
        preferences = self.preferences
        context = f'"{candidate.name}" {preferences.city}'
        dietary = " ".join(preferences.excluded_ingredients)
        diet = "vegetarian" if preferences.vegetarian else ""
        concerns = " ".join(preferences.review_concerns)
        queries = [
            f"{context} official menu {preferences.meal} prices",
            f"{context} reviews good food friendly service {diet} {dietary} {concerns}"[:450],
            f"{context} negative reviews bad slow rude service {diet} {dietary} {concerns}"[:450],
        ]
        for query in queries:
            await self.event("search", "research", query, restaurant=candidate.name)
        results = await asyncio.gather(*(self.web.search(query, 4) for query in queries))
        sources = [source for group in results for source in group]
        await self.record_sources(sources, "research")
        host = (urlsplit(candidate.website).hostname or "").removeprefix("www.")
        official_matches = [
            source for source in results[0] if self.web.likely_official(source, candidate.name)
        ]
        if official_matches:
            candidate.website = official_matches[0].url
            host = (urlsplit(candidate.website).hostname or "").removeprefix("www.")
        menu_sources = [
            source
            for source in results[0]
            if (urlsplit(source.url).hostname or "").removeprefix("www.") == host
        ]
        menu_sources.sort(
            key=lambda source: (
                0
                if any(word in source.url.lower() for word in ("menu", "carta", "speise", ".pdf"))
                else 1
            )
        )
        urls = [candidate.website]
        if menu_sources and normalize_url(menu_sources[0].url) != normalize_url(candidate.website):
            urls.append(menu_sources[0].url)
        review_source = next(
            (
                source
                for source in results[1] + results[2]
                if (urlsplit(source.url).hostname or "").removeprefix("www.") != host
            ),
            None,
        )
        if review_source:
            urls.append(review_source.url)
        pages = await self.web.read(urls)
        sources.extend(pages)
        await self.record_sources(pages, "research")
        links = self.web.menu_links(pages, candidate.website)
        if links:
            menu_pages = await self.web.read(links[:1])
            sources.extend(menu_pages)
            await self.record_sources(menu_pages, "research")
        payload = {
            "restaurant": candidate.model_dump(mode="json"),
            "preferences": preferences.model_dump(mode="json"),
            "sources": self.source_payload(sources),
            "menu_blocks": [
                block
                for source in sources
                if source.coverage != "search_excerpt"
                for block in menu_blocks(source)
            ],
        }
        finding = await self.llm.structured(prompts.EXTRACT, payload, Finding)
        candidate_sources = {source.id: source for source in sources}
        finding = validate_finding(finding, candidate_sources)
        missing_prices = not any(dish.price is not None for dish in finding.dishes)
        missing_negative = not any(
            review.polarity in ("negative", "mixed") for review in finding.reviews
        )
        if (missing_prices or missing_negative) and self.followups < 2 and self.usage.llm_calls < 7:
            self.followups += 1
            query = (
                f"{context} Speisekarte Preise carta precios menu prices"
                if missing_prices
                else f"{context} reviews complaints service slow rude schlechte Bedienung mal servicio"
            )
            await self.event("search", "research", query, restaurant=candidate.name)
            extra = await self.web.search(query, 4)
            sources.extend(extra)
            await self.record_sources(extra, "research")
            if extra:
                payload["sources"] = self.source_payload(sources)
                payload["followup_reason"] = (
                    "Resolve missing published prices"
                    if missing_prices
                    else "Investigate missing negative review evidence"
                )
                candidate_sources = {source.id: source for source in sources}
                finding = validate_finding(
                    await self.llm.structured(prompts.EXTRACT, payload, Finding), candidate_sources
                )
        if finding.menu_url and not (
            any(normalize_url(source.url) == normalize_url(finding.menu_url) for source in sources)
            or any(finding.menu_url in source.text for source in sources)
        ):
            finding.menu_url = None
        if finding.official_website and self.web.known_url(finding.official_website):
            candidate.website = finding.official_website
            host = (urlsplit(candidate.website).hostname or "").removeprefix("www.")
        official_menu = next(
            (
                source.url
                for dish in finding.dishes
                for ref in dish.menu_refs
                if (source := candidate_sources.get(ref.source_id))
                and (urlsplit(source.url).hostname or "").removeprefix("www.") == host
            ),
            None,
        )
        if official_menu:
            finding.menu_url = official_menu
        if not finding.menu_url and finding.dishes:
            ref = finding.dishes[0].menu_refs[0]
            source = candidate_sources[ref.source_id]
            if (urlsplit(source.url).hostname or "").removeprefix("www.") == host:
                finding.menu_url = source.url
        if (
            finding.menu_url
            and (urlsplit(finding.menu_url).hostname or "").removeprefix("www.") != host
        ):
            finding.gaps.append(
                "Menu information comes from a third-party source; confirm the current menu with the restaurant."
            )
        item = recommendation(candidate.name, candidate.website, finding, preferences)
        self.recommendations.append(item)
        await self.event(
            "evidence_found",
            "research",
            f"{candidate.name}: {len(item.dishes)} menu items and {len(item.reviews)} review findings",
            recommendation=item.model_dump(mode="json"),
        )

    async def finish(self):
        await self.event(
            "stage_started",
            "ranking",
            "Checking dietary requirements, prices, and review tradeoffs",
        )
        self.usage.elapsed_seconds = round(time.monotonic() - self.started, 1)
        ranked = sorted(
            (item for item in self.recommendations if item.status != "excluded"), key=rank_key
        )
        excluded = [item for item in self.recommendations if item.status == "excluded"]
        result = Result(
            preferences=self.preferences,
            recommendations=ranked[:3],
            excluded=excluded,
            sources=list(self.web.sources.values()),
            usage=self.usage,
            warnings=list(dict.fromkeys(self.warnings + self.web.errors)),
        )
        self.session.preferences = self.preferences
        self.session.result = result
        self.session.sources = self.web.sources.copy()
        self.session.remember(
            "assistant",
            "Found " + ", ".join(item.name for item in ranked[:3])
            if ranked
            else "No sufficiently supported restaurants found.",
        )
        await self.event(
            "result", "complete", "Research complete", result=result.model_dump(mode="json")
        )
