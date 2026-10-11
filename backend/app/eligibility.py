import re
import unicodedata

from .menu import recover_menu_price
from .schemas import Dish, Finding, Preferences, Recommendation, Reference, Source


def normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def valid_refs(refs: list[Reference], sources: dict[str, Source]) -> list[Reference]:
    return [
        ref
        for ref in refs
        if ref.source_id in sources
        and normalized(ref.quote) in normalized(sources[ref.source_id].text)
    ]


def price_supported(dish: Dish, sources: dict[str, Source] | None = None) -> bool:
    if dish.price is None:
        return False
    for ref in dish.price_refs:
        if normalized(dish.original_name) not in normalized(ref.quote):
            if not any(
                normalized(dish.original_name) in normalized(menu.quote)
                and normalized(ref.quote) in normalized(menu.quote)
                for menu in dish.menu_refs
            ):
                if not sources or ref.source_id not in sources:
                    continue
                if re.search(
                    r"[a-z]", re.sub(r"\b(EUR|GBP|USD)\b", "", ref.quote, flags=re.I), re.I
                ):
                    continue
                text = sources[ref.source_id].text
                linked = False
                for menu in dish.menu_refs:
                    if menu.source_id != ref.source_id:
                        continue
                    start = text.casefold().find(dish.original_name.casefold())
                    if start < 0:
                        continue
                    region = text[start : start + 1200]
                    region = re.split(r"\n\s*#{2,6}\s", region, maxsplit=1)[0]
                    if ref.quote in region:
                        linked = True
                if not linked:
                    continue
        currency_tokens = {
            "EUR": ("€", "eur", "euro"),
            "GBP": ("£", "gbp", "pound"),
            "USD": ("$", "usd", "dollar"),
        }
        tokens = currency_tokens.get(dish.currency or "", ((dish.currency or "").casefold(),))
        currency_evidence = [ref.quote] + [
            other.quote for other in dish.price_refs if other.source_id == ref.source_id
        ]
        if not any(
            token and any(token in normalized(text) for text in currency_evidence)
            for token in tokens
        ):
            continue
        for match in re.findall(r"(?<!\d)\d+(?:[.,]\d{1,2})?(?!\d)", ref.quote):
            if abs(float(match.replace(",", ".")) - dish.price) < 0.001:
                return True
    return False


def validate_finding(finding: Finding, sources: dict[str, Source]) -> Finding:
    finding.location_refs = valid_refs(finding.location_refs, sources)
    if not finding.location_refs:
        finding.address = ""
        finding.location_summary = "Location details could not be verified."
    finding.availability_refs = valid_refs(finding.availability_refs, sources)
    if not finding.availability_refs:
        finding.availability = "unknown"
        finding.availability_summary = "Confirm opening hours and meal availability for your visit."
    validated = []
    for dish in finding.dishes:
        if dish.item_type == "drink":
            continue
        dish.menu_refs = valid_refs(dish.menu_refs, sources)
        if not dish.menu_refs or not any(
            normalized(dish.original_name) in normalized(ref.quote) for ref in dish.menu_refs
        ):
            continue
        dish.price_refs = valid_refs(dish.price_refs, sources)
        recover_menu_price(dish, sources)
        if not price_supported(dish, sources):
            dish.price = None
            dish.price_kind = "unknown"
        elif any(
            re.search(r"\b(from|desde|ab|starting at|a partir)\b", ref.quote, re.I)
            for ref in dish.price_refs
        ):
            dish.price_kind = "from"
        dish.dietary_refs = valid_refs(dish.dietary_refs, sources)
        dish.ingredient_refs = valid_refs(dish.ingredient_refs, sources)
        if not dish.ingredient_refs:
            dish.ingredients = []
        dish.meal_refs = valid_refs(dish.meal_refs, sources)
        if not dish.meal_refs:
            dish.meal_availability = "unknown"
        if not dish.dietary_refs:
            dish.vegetarian = "unknown"
            dish.vegan = "unknown"
        if dish.vegan == "yes":
            explicit_vegan = False
            for ref in dish.dietary_refs:
                quote = normalized(ref.quote)
                name_label = bool(re.search(r"\bvegan[oa]?\b", normalized(dish.original_name)))
                venue_label = bool(
                    re.search(
                        r"(all|100%|fully|entirely|exclusively|completamente|totalmente)\s+vegan|vegan\s+(restaurant|menu|cuisine)|restaurante\s+vegano",
                        quote,
                    )
                )
                heading_label = any(
                    re.search(r"\bvegan[oa]?\b", line, re.I)
                    for line in ref.quote.splitlines()[:1]
                    if normalized(dish.original_name) in normalized(line)
                )
                if name_label or venue_label or heading_label:
                    explicit_vegan = True
            if not explicit_vegan:
                dish.vegan = "unknown"
        for fact in dish.exclusions:
            fact.refs = valid_refs(fact.refs, sources)
            if not fact.refs:
                fact.status = "unknown"
            if fact.status == "absent":
                ingredient = normalized(fact.ingredient)
                variants = {
                    "egg": "egg|eggs|huevo|huevos|ou|ous|ei|eier",
                    "milk": "milk|leche|lait|milch",
                    "dairy": "dairy|lácteos|lacteos|milch",
                    "peanut": "peanut|peanuts|cacahuete|erdnuss",
                }.get(ingredient, re.escape(ingredient))
                absence = any(
                    re.search(
                        rf"\b(no|without|free of|sin|sense|ohne)\s+(?:any\s+)?(?:{variants})\b|\b(?:{variants})[- ]free\b",
                        normalized(ref.quote),
                    )
                    for ref in fact.refs
                )
                if not absence and not (
                    dish.vegan == "yes" and ingredient in {"egg", "milk", "dairy", "honey"}
                ):
                    fact.status = "unknown"
        validated.append(dish)
    finding.dishes = validated
    reviews = []
    seen = set()
    for review in finding.reviews:
        review.refs = valid_refs(review.refs, sources)
        if not review.refs:
            continue
        key = (normalized(review.refs[0].quote), review.aspect, review.polarity)
        if key in seen:
            continue
        seen.add(key)
        if review.review_date and not any(review.review_date in ref.quote for ref in review.refs):
            review.review_date = None
        reviews.append(review)
    finding.reviews = reviews
    return finding


def classify_dish(dish: Dish, preferences: Preferences, availability: str) -> Dish:
    conflicts = []
    unknowns = []
    if preferences.vegetarian:
        if dish.vegetarian == "no":
            conflicts.append("Contains non-vegetarian ingredients.")
        elif dish.vegetarian != "yes" and dish.vegan != "yes":
            unknowns.append("Vegetarian suitability needs confirmation.")
    for ingredient in preferences.excluded_ingredients:
        fact = next(
            (
                fact
                for fact in dish.exclusions
                if normalized(fact.ingredient) == normalized(ingredient)
            ),
            None,
        )
        if fact and fact.status == "present":
            conflicts.append(f"Contains {ingredient}.")
        elif dish.vegan == "yes" and normalized(ingredient) in {"egg", "milk", "dairy", "honey"}:
            pass
        elif not fact or fact.status != "absent":
            unknowns.append(f"Absence of {ingredient} needs confirmation.")
    if preferences.budget is not None:
        if dish.price is None or dish.currency != preferences.currency:
            unknowns.append("A price in your requested currency could not be verified.")
        elif (
            dish.price >= preferences.budget
            if preferences.budget_operator == "lt"
            else dish.price > preferences.budget
        ):
            conflicts.append("Published price exceeds your budget.")
        elif dish.price_kind != "exact":
            unknowns.append("The published price is qualified; confirm the final price.")
    if dish.menu_category in ("set_menu", "special", "unknown"):
        unknowns.append("Confirm menu conditions and availability of this item.")
    if (
        dish.meal_availability not in ("any", "unknown", preferences.meal)
        and preferences.meal != "any"
    ):
        conflicts.append(
            f"This price or item is listed for {dish.meal_availability}, not {preferences.meal}."
        )
    if availability == "conflict":
        conflicts.append("Published availability conflicts with your visit.")
    elif availability == "unknown" and (preferences.visit_date or preferences.meal != "any"):
        unknowns.append("Opening hours and availability for your meal need confirmation.")
    dish.status = "excluded" if conflicts else "confirmation" if unknowns else "supported"
    dish.reasons = conflicts + unknowns
    return dish


def recommendation(
    name: str, website: str, finding: Finding, preferences: Preferences
) -> Recommendation:
    dishes = [classify_dish(dish, preferences, finding.availability) for dish in finding.dishes]
    statuses = {dish.status for dish in dishes}
    status = (
        "supported"
        if "supported" in statuses
        else "confirmation"
        if "confirmation" in statuses or not dishes
        else "excluded"
    )
    gaps = list(finding.gaps)
    if not dishes:
        gaps.append("No menu items with verifiable supporting text were retrieved.")
    if not finding.menu_url:
        gaps.append("An accessible menu link could not be verified.")
    if not any(review.polarity in ("positive", "mixed") for review in finding.reviews):
        gaps.append("No positive review evidence was retrieved.")
    if not any(review.polarity in ("negative", "mixed") for review in finding.reviews):
        gaps.append(
            "No negative review evidence was retrieved; this does not establish good service."
        )
    if not any(
        review.aspect == "service" and review.source_type == "customer_review"
        for review in finding.reviews
    ):
        gaps.append("No customer review evidence about service was retrieved.")
    negative_service = [
        review
        for review in finding.reviews
        if review.aspect == "service" and review.polarity in ("negative", "mixed")
    ]
    positives = [
        review
        for review in finding.reviews
        if review.polarity in ("positive", "mixed") and review.source_type == "customer_review"
    ]
    matching = [dish for dish in dishes if dish.status == "supported"]
    explanation = (
        f"{len(matching)} menu option{'s' if len(matching) != 1 else ''} supported by the retrieved evidence."
        if matching
        else "Potential option; check the listed uncertainties before choosing."
    )
    if status == "excluded":
        explanation = "The retrieved menu options conflict with your requirements."
    if positives:
        explanation += f" Review evidence: {positives[0].summary}"
    if negative_service:
        explanation += f" Service concern: {negative_service[0].summary}"
    return Recommendation(
        name=name,
        website=website,
        menu_url=finding.menu_url,
        address=finding.address,
        location_summary=finding.location_summary,
        location_refs=finding.location_refs,
        status=status,
        explanation=explanation,
        dishes=dishes,
        reviews=finding.reviews,
        availability_summary=finding.availability_summary,
        availability_refs=finding.availability_refs,
        gaps=list(dict.fromkeys(gaps)),
    )


def rank_key(item: Recommendation) -> tuple:
    customer_service = [
        review
        for review in item.reviews
        if review.source_type == "customer_review" and review.aspect == "service"
    ]
    negative = len(
        {
            (review.refs[0].source_id, normalized(review.refs[0].quote))
            for review in customer_service
            if review.polarity in ("negative", "mixed")
        }
    )
    service_risk = 2 + negative if negative else 0 if customer_service else 1
    food = sum(review.polarity == "positive" and review.aspect == "food" for review in item.reviews)
    supported = sum(dish.status == "supported" for dish in item.dishes)
    return (
        0 if item.status == "supported" else 1,
        service_risk,
        -supported,
        -food,
        0 if item.location_refs else 1,
        len(item.gaps),
    )
