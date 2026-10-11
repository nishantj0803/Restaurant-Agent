# Tablefind

A restaurant finder built with FastAPI, React, Gemini, and Tavily. Shows menu prices, ingredients, and review summaries in English with source links. Supports follow-up questions.

## Setup

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and Node.js 20.19+ or 22.12+.

Copy `.env.example` to `.env` and add your Gemini and Tavily API keys.

Backend:

```sh
cd backend
uv sync --python 3.12
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app
```

Frontend, in another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173. Restart the backend after changing `.env`.

## Assumptions

- Dietary restrictions apply only when requested.
- Budget covers one main or breakfast item per person, excluding extras.
- Dates use the traveller's timezone; proximity uses published location details.

## Limitations

- Menus and reviews may be incomplete or outdated. Image menus and scanned PDFs are unsupported.
- Ingredients, translations, and opening hours need confirmation. No allergy or availability guarantees.
- Chat memory expires after one idle hour and resets on refresh or backend restart.
- Tested live in Barcelona and Berlin. Local use only; no authentication or bookings.
