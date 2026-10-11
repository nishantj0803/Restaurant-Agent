import asyncio
import json
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .config import Settings
from .schemas import Usage

T = TypeVar("T", bound=BaseModel)


class ProviderError(Exception):
    pass


def generation_schema(schema: type[BaseModel]) -> dict:
    def strip_array_bounds(node):
        if isinstance(node, dict):
            return {
                key: strip_array_bounds(value)
                for key, value in node.items()
                if key not in {"minItems", "maxItems"}
            }
        if isinstance(node, list):
            return [strip_array_bounds(value) for value in node]
        return node

    # Gemini rejects bounded arrays in this nested schema; Pydantic validates the bounds.
    return strip_array_bounds(schema.model_json_schema())


class Gemini:
    def __init__(self, client: httpx.AsyncClient, settings: Settings, usage: Usage):
        self.client = client
        self.settings = settings
        self.usage = usage

    async def structured(self, instruction: str, payload: dict, schema: type[T]) -> T:
        body = {
            "systemInstruction": {
                "parts": [{"text": instruction + "\nReturn only the requested JSON structure."}]
            },
            "contents": [
                {"role": "user", "parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}
            ],
            "generationConfig": {
                "temperature": 0.15,
                "responseMimeType": "application/json",
                "responseJsonSchema": generation_schema(schema),
            },
        }
        if self.settings.gemini_model.startswith("gemini-2.5-flash"):
            body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{self.settings.gemini_model}:generateContent"
        for attempt in range(2):
            if self.usage.llm_calls >= 8:
                raise ProviderError(
                    "The model-call limit was reached. Try a more specific request."
                )
            self.usage.llm_calls += 1
            try:
                response = await self.client.post(
                    endpoint,
                    headers={"x-goog-api-key": self.settings.gemini_api_key.get_secret_value()},
                    json=body,
                    timeout=65,
                )
            except httpx.HTTPError:
                if attempt == 0:
                    await asyncio.sleep(1)
                    continue
                raise ProviderError("Gemini could not be reached. Please retry.") from None
            if response.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                await asyncio.sleep(3 if response.status_code == 429 else 1)
                continue
            if response.status_code >= 400:
                messages = {
                    400: "Gemini rejected the request. Check GEMINI_MODEL and structured-output support.",
                    401: "Gemini authentication failed. Check GEMINI_API_KEY.",
                    403: "Gemini access was denied. Check your key and project access.",
                    404: "The configured Gemini model is unavailable. Update GEMINI_MODEL.",
                    429: "Gemini's quota was reached. Wait before retrying or check your account limits.",
                }
                raise ProviderError(
                    messages.get(response.status_code, "Gemini returned a service error.")
                )
            data = response.json()
            tokens = data.get("usageMetadata", {})
            self.usage.input_tokens += tokens.get("promptTokenCount", 0)
            self.usage.output_tokens += tokens.get("candidatesTokenCount", 0) + tokens.get(
                "thoughtsTokenCount", 0
            )
            try:
                parts = data["candidates"][0]["content"]["parts"]
                content = "".join(part.get("text", "") for part in parts if not part.get("thought"))
                return schema.model_validate_json(content)
            except (KeyError, IndexError, ValidationError):
                if attempt == 0:
                    body["contents"].append(
                        {
                            "role": "user",
                            "parts": [
                                {"text": "Return complete JSON matching the schema exactly."}
                            ],
                        }
                    )
                    continue
                raise ProviderError(
                    "Gemini returned incomplete structured data. Please retry."
                ) from None
        raise ProviderError("Gemini did not return a usable response.")
