import re

from .schemas import Dish, Reference, Source

PRICE = re.compile(
    r"(?:(€|EUR|£|GBP)\s*(\d+(?:[.,]\d{1,2})?)|(\d+(?:[.,]\d{1,2})?)\s*(€|EUR|£|GBP))(?!\d)", re.I
)


def menu_blocks(source: Source) -> list[dict]:
    headings = list(re.finditer(r"(?m)^#{3,6}\s+(.+)$", source.text))
    blocks = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(source.text)
        quote = source.text[heading.start() : end].strip()
        if len(quote) <= 1200 and PRICE.search(quote):
            blocks.append(
                {"source_id": source.id, "name": heading.group(1).strip(), "quote": quote}
            )
    return blocks


def matching_block(dish: Dish, sources: dict[str, Source]) -> tuple[Source, str] | None:
    name = " ".join(dish.original_name.casefold().split())
    for ref in dish.menu_refs:
        source = sources.get(ref.source_id)
        if not source:
            continue
        for block in menu_blocks(source):
            if " ".join(block["name"].casefold().split()) == name:
                return source, block["quote"]
    return None


def recover_menu_price(dish: Dish, sources: dict[str, Source]):
    found = matching_block(dish, sources)
    if not found:
        return
    source, block = found
    prices = list(PRICE.finditer(block))
    if len(prices) != 1:
        return
    match = prices[0]
    symbol = (match.group(1) or match.group(4)).upper()
    dish.price = float((match.group(2) or match.group(3)).replace(",", "."))
    dish.currency = "EUR" if symbol in {"€", "EUR"} else "GBP"
    dish.price_kind = (
        "from" if re.search(r"\b(from|desde|ab|starting at|a partir)\b", block, re.I) else "exact"
    )
    dish.price_refs = [Reference(source_id=source.id, quote=block)]
    if "menu" not in dish.original_name.casefold() and dish.menu_category == "unknown":
        dish.menu_category = "regular"
