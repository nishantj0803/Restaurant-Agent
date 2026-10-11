import httpx
import pytest

from app.config import Settings
from app.schemas import Source, Usage
from app.web import Web, public_url


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/menu",
        "http://127.0.0.1",
        "http://10.1.2.3",
        "http://169.254.169.254",
        "http://[::1]",
        "http://hotel.local",
        "https://user:password@example.com",
        "file:///etc/passwd",
        "https://example.com:8080/menu",
        "javascript:alert(1)",
    ],
)
def test_private_and_non_public_urls_rejected(url):
    assert not public_url(url)


@pytest.mark.parametrize(
    "url", ["https://restaurant.example/menu", "https://www.restaurant.de/speisekarte.pdf"]
)
def test_public_urls_accepted(url):
    assert public_url(url)


async def test_extraction_partial_failure_preserves_success():
    def respond(request):
        return httpx.Response(
            200,
            json={
                "results": [{"url": "https://restaurant.example/menu", "raw_content": "Bowl 15 €"}],
                "failed_results": [{"url": "https://reviews.example/place", "error": "blocked"}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        web = Web(client, Settings(_env_file=None), Usage())
        results = await web.read(
            ["https://restaurant.example/menu", "https://reviews.example/place"]
        )
    assert len(results) == 1
    assert results[0].coverage == "extracted_page"
    assert any("reviews.example" in error for error in web.errors)


def test_menu_links_come_from_content():
    page = Source(
        id="s1",
        url="https://restaurant.example",
        title="Home",
        coverage="extracted_page",
        text="[Menu](https://restaurant.example/menu) [Book](https://restaurant.example/book) [Other menu](https://unrelated.example/menu)",
    )
    assert Web.menu_links([page], "https://restaurant.example") == [
        "https://restaurant.example/menu"
    ]


def test_contextual_excerpts_from_same_url_are_not_lost():
    web = Web(None, Settings(_env_file=None), Usage())
    positive = web.add_source(
        "https://reviews.example/place", "Review", "Great food", "search_excerpt"
    )
    negative = web.add_source(
        "https://reviews.example/place", "Review", "Slow service", "search_excerpt"
    )
    duplicate = web.add_source(
        "https://reviews.example/place", "Review", "Great food", "search_excerpt"
    )
    assert positive.id != negative.id
    assert duplicate.id == positive.id
    assert len(web.sources) == 2


def test_relative_menu_links_are_resolved():
    page = Source(
        id="s1",
        url="https://restaurant.example/en/home",
        title="Home",
        coverage="extracted_page",
        text="[Menu](../menu) [Spanish carta](../../carta.pdf)",
    )
    assert set(Web.menu_links([page], "https://restaurant.example")) == {
        "https://restaurant.example/menu",
        "https://restaurant.example/carta.pdf",
    }
