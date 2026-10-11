import pytest

from app.eligibility import classify_dish, recommendation, validate_finding
from app.schemas import DietaryFact, Dish, Finding, Preferences, Reference, Review, Source


@pytest.fixture
def preferences():
    return Preferences(
        city="Barcelona", meal="lunch", budget=20, currency="EUR", excluded_ingredients=["egg"]
    )


@pytest.fixture
def dish():
    return Dish(
        original_name="Bowl",
        english_name="Bowl",
        description="Vegetables",
        price=15,
        currency="EUR",
        price_kind="exact",
        menu_category="regular",
        vegetarian="yes",
        vegan="unknown",
    )


def test_vegetarian_does_not_establish_egg_absence(dish, preferences):
    result = classify_dish(dish, preferences, "compatible")
    assert result.status == "confirmation"
    assert "Absence of egg needs confirmation." in result.reasons


def test_vegan_supports_egg_exclusion(dish, preferences):
    dish.vegan = "yes"
    assert classify_dish(dish, preferences, "compatible").status == "supported"


def test_vegan_does_not_establish_peanut_absence(dish, preferences):
    dish.vegan = "yes"
    preferences.excluded_ingredients = ["peanut"]
    assert classify_dish(dish, preferences, "compatible").status == "confirmation"


def test_explicit_egg_content_is_excluded_even_if_inconsistent_vegan_label(dish, preferences):
    dish.vegan = "yes"
    dish.exclusions = [DietaryFact(ingredient="egg", status="present")]
    assert classify_dish(dish, preferences, "compatible").status == "excluded"


@pytest.mark.parametrize(
    "operator,amount,status",
    [
        ("lt", 20, "excluded"),
        ("lte", 20, "supported"),
        ("lt", 19.99, "supported"),
        ("lte", 20.01, "excluded"),
    ],
)
def test_budget_boundary(dish, preferences, operator, amount, status):
    dish.vegan = "yes"
    dish.price = amount
    preferences.budget_operator = operator
    assert classify_dish(dish, preferences, "compatible").status == status


@pytest.mark.parametrize(
    "price_kind,price,currency",
    [("from", 12, "EUR"), ("unknown", None, "EUR"), ("exact", 12, "USD")],
)
def test_unverified_price_cannot_be_supported(dish, preferences, price_kind, price, currency):
    dish.vegan = "yes"
    dish.price_kind, dish.price, dish.currency = price_kind, price, currency
    assert classify_dish(dish, preferences, "compatible").status == "confirmation"


def test_opening_hours_unknown_and_closed(dish, preferences):
    dish.vegan = "yes"
    assert (
        classify_dish(dish.model_copy(deep=True), preferences, "unknown").status == "confirmation"
    )
    assert classify_dish(dish.model_copy(deep=True), preferences, "conflict").status == "excluded"


def source(text):
    return Source(
        id="s1",
        url="https://restaurant.example/menu",
        title="Menu",
        text=text,
        coverage="extracted_page",
    )


def ref(quote):
    return Reference(source_id="s1", quote=quote)


def test_fabricated_dish_and_quote_removed():
    sources = {"s1": source("Ensalada 14 €")}
    fake = Dish(
        original_name="Pasta", english_name="Pasta", description="", menu_refs=[ref("Pasta 12 €")]
    )
    finding = validate_finding(Finding(dishes=[fake]), sources)
    assert finding.dishes == []


def test_price_from_another_dish_rejected():
    sources = {"s1": source("Bowl 15 €\nPasta 12 €")}
    item = Dish(
        original_name="Bowl",
        english_name="Bowl",
        description="",
        price=12,
        currency="EUR",
        price_kind="exact",
        menu_refs=[ref("Bowl 15 €")],
        price_refs=[ref("Pasta 12 €")],
    )
    result = validate_finding(Finding(dishes=[item]), sources)
    assert result.dishes[0].price is None


def test_original_name_and_local_decimal_price_preserved():
    text = "Ensalada vegana 14,50 €"
    item = Dish(
        original_name="Ensalada",
        english_name="Salad",
        description="",
        price=14.5,
        currency="EUR",
        price_kind="exact",
        vegan="yes",
        menu_refs=[ref(text)],
        price_refs=[ref(text)],
        dietary_refs=[ref(text)],
    )
    result = validate_finding(Finding(dishes=[item]), {"s1": source(text)})
    assert result.dishes[0].price == 14.5
    assert result.dishes[0].original_name == "Ensalada"


def test_from_qualifier_cannot_be_discarded():
    text = "Bowl from €12"
    item = Dish(
        original_name="Bowl",
        english_name="Bowl",
        description="",
        price=12,
        currency="EUR",
        price_kind="exact",
        menu_refs=[ref(text)],
        price_refs=[ref(text)],
    )
    result = validate_finding(Finding(dishes=[item]), {"s1": source(text)})
    assert result.dishes[0].price_kind == "from"


def test_missing_dietary_refs_downgrade_claim():
    text = "Bowl 15 €"
    item = Dish(
        original_name="Bowl",
        english_name="Bowl",
        description="",
        vegetarian="yes",
        vegan="yes",
        menu_refs=[ref(text)],
        dietary_refs=[ref("All dishes are vegan")],
    )
    result = validate_finding(Finding(dishes=[item]), {"s1": source(text)})
    assert result.dishes[0].vegan == "unknown"
    assert result.dishes[0].vegetarian == "unknown"


def test_unretrieved_review_removed_and_missing_negative_disclosed(preferences):
    review = Review(
        polarity="positive",
        aspect="food",
        summary="Great food",
        source_type="customer_review",
        refs=[ref("Amazing food")],
    )
    finding = validate_finding(Finding(reviews=[review]), {"s1": source("Opening hours")})
    result = recommendation("Place", "https://restaurant.example", finding, preferences)
    assert result.reviews == []
    assert any("No negative review evidence" in gap for gap in result.gaps)


def test_empty_menu_is_uncertain_not_an_invented_match(preferences):
    item = recommendation("Place", "https://restaurant.example", Finding(), preferences)
    assert item.status == "confirmation"
    assert item.dishes == []


def test_mixed_review_keeps_food_and_service_findings():
    text = "Good food but slow service."
    refs = [ref(text)]
    finding = Finding(
        reviews=[
            Review(
                polarity="positive",
                aspect="food",
                summary="Good food",
                source_type="customer_review",
                refs=refs,
            ),
            Review(
                polarity="negative",
                aspect="service",
                summary="Slow service",
                source_type="customer_review",
                refs=refs,
            ),
        ]
    )
    result = validate_finding(finding, {"s1": source(text)})
    assert {review.aspect for review in result.reviews} == {"food", "service"}


def test_price_recovered_from_real_separate_menu_blocks():
    text = "##### Tofu Bowl\n\nBlack rice, smoked tofu, peas, broccoli\n\n14,00€\n\n##### Heura Bowl\n\nRice and vegetables\n\n14,50€"
    item = Dish(
        original_name="Tofu Bowl",
        english_name="Tofu bowl",
        description="",
        price=14,
        currency="EUR",
        price_kind="exact",
        menu_refs=[ref("Tofu Bowl")],
        price_refs=[ref("14,00€")],
    )
    result = validate_finding(Finding(dishes=[item]), {"s1": source(text)})
    assert result.dishes[0].price == 14
    assert "Tofu Bowl" in result.dishes[0].price_refs[0].quote
    assert result.dishes[0].menu_category == "regular"


def test_other_dish_price_not_associated_across_heading():
    text = "##### Bowl\n\nVegetables\n\n##### Pasta\n\n12 €"
    item = Dish(
        original_name="Bowl",
        english_name="Bowl",
        description="",
        price=12,
        currency="EUR",
        price_kind="exact",
        menu_refs=[ref("Bowl")],
        price_refs=[ref("12 €")],
    )
    result = validate_finding(Finding(dishes=[item]), {"s1": source(text)})
    assert result.dishes[0].price is None


def test_unretrieved_ingredients_removed():
    item = Dish(
        original_name="Bowl",
        english_name="Bowl",
        description="",
        ingredients=["tofu"],
        menu_refs=[ref("Bowl")],
        ingredient_refs=[ref("tofu")],
    )
    result = validate_finding(Finding(dishes=[item]), {"s1": source("Bowl 14 €")})
    assert result.dishes[0].ingredients == []


def test_ingredient_list_does_not_establish_egg_absence_or_vegan_label():
    text = "##### Heura Bowl\n\nRice, vegetables, vegan mayonnaise\n\n14 €"
    item = Dish(
        original_name="Heura Bowl",
        english_name="Heura bowl",
        description="",
        vegan="yes",
        menu_refs=[ref("Heura Bowl")],
        dietary_refs=[ref("Rice, vegetables, vegan mayonnaise")],
        exclusions=[
            DietaryFact(
                ingredient="egg", status="absent", refs=[ref("Rice, vegetables, vegan mayonnaise")]
            )
        ],
    )
    result = validate_finding(Finding(dishes=[item]), {"s1": source(text)})
    assert result.dishes[0].vegan == "unknown"
    assert result.dishes[0].exclusions[0].status == "unknown"


def test_explicit_egg_free_label_retained():
    text = "Bowl: rice and vegetables, no eggs."
    item = Dish(
        original_name="Bowl",
        english_name="Bowl",
        description="",
        menu_refs=[ref(text)],
        exclusions=[DietaryFact(ingredient="egg", status="absent", refs=[ref(text)])],
    )
    result = validate_finding(Finding(dishes=[item]), {"s1": source(text)})
    assert result.dishes[0].exclusions[0].status == "absent"


def test_lunch_price_cannot_satisfy_dinner(dish, preferences):
    preferences.vegetarian = False
    preferences.excluded_ingredients = []
    preferences.meal = "dinner"
    dish.meal_availability = "lunch"
    assert classify_dish(dish, preferences, "compatible").status == "excluded"


def test_drinks_are_not_returned_as_meal_options():
    item = Dish(
        original_name="Coca Cola",
        english_name="Coca Cola",
        description="",
        item_type="drink",
        menu_refs=[ref("Coca Cola 3 €")],
    )
    result = validate_finding(Finding(dishes=[item]), {"s1": source("Coca Cola 3 €")})
    assert result.dishes == []
