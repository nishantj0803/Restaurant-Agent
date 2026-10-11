import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/health", (route) =>
    route.fulfill({ json: { status: "ready", missing_keys: [] } }),
  );
});

test("a missing city is clarified", async ({ page }) => {
  await page.route("**/api/recommendations", (route) =>
    route.fulfill({
      contentType: "application/x-ndjson",
      body:
        JSON.stringify({
          type: "clarification",
          stage: "preferences",
          message: "Which city will you be visiting?",
          data: {},
          timestamp: new Date().toISOString(),
        }) + "\n",
    }),
  );
  await page.goto("/");
  await page
    .getByLabel("Message Tablefind")
    .fill("Germany tomorrow, vegetarian lunch under €20");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(
    page.getByText("Which city will you be visiting?"),
  ).toBeVisible();
});

test("configuration errors are shown without a fabricated result", async ({
  page,
}) => {
  await page.route("**/api/recommendations", (route) =>
    route.fulfill({
      contentType: "application/x-ndjson",
      body:
        JSON.stringify({
          type: "error",
          stage: "configuration",
          message: "Add GEMINI_API_KEY and TAVILY_API_KEY to .env",
          data: {},
          timestamp: new Date().toISOString(),
        }) + "\n",
    }),
  );
  await page.goto("/");
  await page.getByLabel("Message Tablefind").fill("Dinner in Berlin under €25");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("alert")).toContainText("GEMINI_API_KEY");
  await expect(page.getByRole("heading", { name: /options in/ })).toHaveCount(
    0,
  );
});

test("mobile layout fits the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByLabel("Message Tablefind")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("recommendations retain menu names, prices, review tradeoffs, and evidence links", async ({
  page,
}) => {
  const now = new Date().toISOString();
  const refs = [{ source_id: "s1", quote: "Ensalada vegana 15 €" }];
  const preferences = {
    city: "Barcelona",
    country: "Spain",
    meal: "lunch",
    visit_date: null,
    budget: 20,
    currency: "EUR",
    budget_operator: "lt",
    vegetarian: true,
    excluded_ingredients: ["egg"],
    location_preference: "city centre",
    review_concerns: ["service"],
    assumptions: ["Budget covers one main dish."],
  };
  const item = {
    name: "Sample Restaurant",
    website: "https://restaurant.example",
    menu_url: "https://restaurant.example/menu",
    address: "Example street",
    location_summary: "Central neighbourhood",
    location_refs: [],
    status: "confirmation",
    explanation: "Potential option; confirm lunch availability.",
    dishes: [
      {
        original_name: "Ensalada vegana",
        english_name: "Vegan salad",
        description: "Vegetables and chickpeas",
        ingredients: ["vegetables", "chickpeas"],
        ingredient_refs: refs,
        price: 15,
        currency: "EUR",
        price_kind: "exact",
        menu_category: "regular",
        vegetarian: "yes",
        vegan: "yes",
        menu_refs: refs,
        dietary_refs: refs,
        price_refs: refs,
        status: "confirmation",
        reasons: ["Confirm lunch availability."],
      },
    ],
    reviews: [
      {
        polarity: "positive",
        aspect: "food",
        summary: "Customers liked the fresh food.",
        source_type: "customer_review",
        review_date: null,
        refs: [{ source_id: "s2", quote: "Fresh food, but service was slow." }],
      },
      {
        polarity: "negative",
        aspect: "service",
        summary: "A customer reported slow service.",
        source_type: "customer_review",
        review_date: null,
        refs: [{ source_id: "s2", quote: "Fresh food, but service was slow." }],
      },
    ],
    availability_summary: "Confirm lunch opening hours.",
    availability_refs: [],
    gaps: ["Opening hours are unverified."],
  };
  const sources = [
    {
      id: "s1",
      url: "https://restaurant.example/menu",
      title: "Menu",
      coverage: "extracted_page",
      retrieved_at: now,
      published_date: null,
    },
    {
      id: "s2",
      url: "https://reviews.example/place",
      title: "Customer review",
      coverage: "search_excerpt",
      retrieved_at: now,
      published_date: null,
    },
  ];
  const events = [
    {
      type: "preferences",
      stage: "preferences",
      message: "Preferences ready",
      data: { preferences },
      timestamp: now,
    },
    {
      type: "result",
      stage: "complete",
      message: "Research complete",
      data: {
        result: {
          preferences,
          recommendations: [item],
          excluded: [],
          sources,
          usage: {
            searches: 5,
            documents: 2,
            llm_calls: 3,
            input_tokens: 50,
            output_tokens: 40,
            elapsed_seconds: 20,
          },
          warnings: [],
        },
      },
      timestamp: now,
    },
  ];
  await page.route("**/api/recommendations", (route) =>
    route.fulfill({
      contentType: "application/x-ndjson",
      body: events.map((event) => JSON.stringify(event)).join("\n") + "\n",
    }),
  );
  await page.goto("/");
  await page
    .getByLabel("Message Tablefind")
    .fill("Vegetarian lunch in Barcelona under €20, no eggs");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(
    page.getByRole("heading", { name: "Sample Restaurant" }),
  ).toBeVisible();
  await expect(
    page.getByText("Ensalada vegana", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("€15.00")).toBeVisible();
  await expect(page.getByText("Listed ingredients:")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "What people liked" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "What to watch for" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Menu", exact: true }).first(),
  ).toHaveAttribute("href", "https://restaurant.example/menu");
  await page.locator(".review-item .evidence summary").first().click();
  await expect(
    page.getByText(/Search excerpt · Retrieved/).first(),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("follow-up messages keep the session and earlier conversation", async ({
  page,
}) => {
  const sessionId = "a".repeat(32);
  let count = 0;
  await page.route("**/api/recommendations", (route) => {
    const request = route.request().postDataJSON();
    count += 1;
    if (count === 2) expect(request.session_id).toBe(sessionId);
    const message =
      count === 1
        ? "Which city will you be visiting?"
        : "I can search Berlin with those preferences.";
    const events = [
      {
        type: "session",
        stage: "session",
        message: "",
        data: { session_id: sessionId },
      },
      {
        type: count === 1 ? "clarification" : "answer",
        stage: "complete",
        message,
        data: { refs: [], sources: [] },
      },
    ];
    return route.fulfill({
      contentType: "application/x-ndjson",
      body: events.map((event) => JSON.stringify(event)).join("\n") + "\n",
    });
  });
  await page.goto("/");
  await page.getByLabel("Message Tablefind").fill("Germany, lunch under €20");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(
    page.getByText("Which city will you be visiting?"),
  ).toBeVisible();
  await page.getByLabel("Message Tablefind").fill("Berlin");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(
    page.getByText("I can search Berlin with those preferences."),
  ).toBeVisible();
  await expect(
    page.getByText("Germany, lunch under €20", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Berlin", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "New chat" }).click();
  await expect(
    page.getByRole("heading", { name: "Where are you eating?" }),
  ).toBeVisible();
  await expect(
    page.getByText("Germany, lunch under €20", { exact: true }),
  ).toHaveCount(0);
});

test("a follow-up reply scrolls above the composer in a long conversation", async ({
  page,
}) => {
  let count = 0;
  await page.route("**/api/recommendations", (route) => {
    count += 1;
    return route.fulfill({
      contentType: "application/x-ndjson",
      body:
        JSON.stringify({
          type: "answer",
          stage: "complete",
          message:
            count === 1
              ? "Menu evidence.\n".repeat(90)
              : "The menu does not list eggs.",
          data: {},
        }) + "\n",
    });
  });
  await page.goto("/");
  await page.getByLabel("Message Tablefind").fill("Show the evidence");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("button", { name: "Stop research" })).toHaveCount(
    0,
  );
  await page.getByLabel("Message Tablefind").fill("Does it list eggs?");
  await page.getByRole("button", { name: "Send message" }).click();
  const reply = page.getByText("The menu does not list eggs.");
  await expect(reply).toBeVisible();
  await expect
    .poll(async () => {
      const answer = await reply.boundingBox();
      const composer = await page.locator(".composer-area").boundingBox();
      return (
        !!answer &&
        !!composer &&
        answer.y > 0 &&
        answer.y + answer.height <= composer.y
      );
    })
    .toBe(true);
});
