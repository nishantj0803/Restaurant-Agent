import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .agent import Agent
from .config import get_settings
from .llm import ProviderError
from .schemas import Event, Request
from .sessions import Sessions

app = FastAPI(title="Tablefind", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
logger = logging.getLogger("tablefind")
sessions = Sessions()


@app.get("/api/health")
async def health():
    settings = get_settings()
    return {
        "status": "ready" if not settings.missing_keys else "configuration_required",
        "missing_keys": settings.missing_keys,
        "model": settings.gemini_model,
    }


@app.post("/api/recommendations")
async def recommendations(request: Request):
    settings = get_settings()

    async def stream():
        if settings.missing_keys:
            event = Event(
                type="error",
                stage="configuration",
                message="Add "
                + " and ".join(settings.missing_keys)
                + " to the root .env file, then restart the backend.",
            )
            yield event.model_dump_json() + "\n"
            return
        queue = asyncio.Queue()
        session = sessions.get(request.session_id)
        if session is None:
            yield (
                Event(
                    type="error",
                    stage="session",
                    message="This conversation expired. Start a new chat.",
                ).model_dump_json()
                + "\n"
            )
            return
        yield (
            Event(
                type="session", stage="session", message="", data={"session_id": session.id}
            ).model_dump_json()
            + "\n"
        )
        agent = Agent(settings, request, queue.put, session)

        async def run():
            try:
                async with asyncio.timeout(settings.request_timeout_seconds):
                    async with session.lock:
                        await agent.run()
            except TimeoutError:
                await queue.put(
                    Event(
                        type="warning",
                        stage="research",
                        message="The research deadline was reached. Some evidence is incomplete.",
                    )
                )
                if agent.preferences is not None and agent.recommendations:
                    agent.warnings.append(
                        "The request deadline was reached; these are partial results."
                    )
                    await agent.finish()
                else:
                    await queue.put(
                        Event(
                            type="error",
                            stage="research",
                            message="Research timed out before usable recommendations were ready. Please retry with a more specific request.",
                        )
                    )
            except ProviderError as exc:
                await queue.put(Event(type="error", stage="provider", message=str(exc)))
            except Exception:
                logger.exception("Restaurant research failed")
                await queue.put(
                    Event(
                        type="error",
                        stage="research",
                        message="Research could not finish. Check the backend logs and retry.",
                    )
                )
            finally:
                await queue.put(None)

        task = asyncio.create_task(run())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event.model_dump_json() + "\n"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
