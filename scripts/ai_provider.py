"""Small AI provider adapters for structured JSON generation."""

from __future__ import annotations

import json
from typing import Any


def extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text

    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                chunks.append(text)
    return "\n".join(chunks)


def call_structured_ai(
    *,
    provider: str,
    system_prompt: str,
    user_text: str,
    model: str,
    api_key: str,
    schema_name: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    normalized_provider = provider.strip().lower()
    if normalized_provider == "openai":
        return call_openai_structured(
            system_prompt=system_prompt,
            user_text=user_text,
            model=model,
            api_key=api_key,
            schema_name=schema_name,
            schema=schema,
        )
    if normalized_provider == "anthropic":
        return call_anthropic_structured(
            system_prompt=system_prompt,
            user_text=user_text,
            model=model,
            api_key=api_key,
            schema=schema,
        )
    if normalized_provider in {"gemini", "google", "google-gemini"}:
        return call_gemini_structured(
            system_prompt=system_prompt,
            user_text=user_text,
            model=model,
            api_key=api_key,
            schema=schema,
        )
    raise RuntimeError(f"Unsupported AI provider: {provider}")


def call_openai_structured(
    *,
    system_prompt: str,
    user_text: str,
    model: str,
    api_key: str,
    schema_name: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency for provider `openai`: install with `python3 -m pip install openai`."
        ) from exc

    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_text}],
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": schema,
            }
        },
    )
    return parse_json_response(extract_response_text(response))


def call_anthropic_structured(
    *,
    system_prompt: str,
    user_text: str,
    model: str,
    api_key: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency for provider `anthropic`: install with `python3 -m pip install anthropic`."
        ) from exc

    schema_instruction = (
        "Return only valid JSON. Do not include Markdown fences or commentary. "
        "The JSON must satisfy this schema:\n"
        f"{json.dumps(schema, indent=2)}"
    )
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4000,
        system=f"{system_prompt}\n\n{schema_instruction}",
        messages=[{"role": "user", "content": user_text}],
    )
    chunks = [
        getattr(item, "text", "")
        for item in getattr(response, "content", []) or []
        if getattr(item, "type", "") == "text"
    ]
    return parse_json_response("\n".join(chunks))


def call_gemini_structured(
    *,
    system_prompt: str,
    user_text: str,
    model: str,
    api_key: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency for provider `gemini`: install with `python3 -m pip install google-genai`."
        ) from exc

    prompt = (
        f"{system_prompt}\n\n"
        "Return only valid JSON. Do not include Markdown fences or commentary.\n\n"
        f"{user_text}"
    )
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "response_format": {
                "text": {
                    "mime_type": "application/json",
                    "schema": schema,
                }
            }
        },
    )
    return parse_json_response(getattr(response, "text", ""))


def parse_json_response(response_text: str) -> dict[str, Any]:
    if not response_text:
        raise RuntimeError("AI provider response did not contain text output.")
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AI provider response was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("AI provider response must be a JSON object.")
    return data
