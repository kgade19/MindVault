"""Anthropic Claude client — streaming, non-streaming, and Vision calls."""
from __future__ import annotations

import base64
from collections.abc import Generator
from pathlib import Path

import anthropic

from mindvault.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def chat(
    messages: list[dict],
    system: str = "",
    max_tokens: int = 2048,
) -> str:
    """Non-streaming chat call. Returns full response text."""
    kwargs: dict = {"model": CLAUDE_MODEL, "max_tokens": max_tokens, "messages": messages}
    if system:
        kwargs["system"] = system
    response = get_client().messages.create(**kwargs)
    return response.content[0].text


def stream_chat(
    messages: list[dict],
    system: str = "",
    max_tokens: int = 2048,
) -> Generator[str, None, None]:
    """Streaming chat call. Yields text deltas."""
    kwargs: dict = {"model": CLAUDE_MODEL, "max_tokens": max_tokens, "messages": messages}
    if system:
        kwargs["system"] = system
    with get_client().messages.stream(**kwargs) as stream:
        for text in stream.text_stream:
            yield text


def describe_image(image_bytes: bytes, media_type: str = "image/jpeg", prompt: str = "") -> str:
    """Send an image to Claude Vision and return the description."""
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    user_prompt = prompt or (
        "Please describe this image in detail, extracting all text visible and summarising "
        "any diagrams, charts, or visual content. Preserve all specific names, numbers, and identifiers."
    )
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": user_prompt},
            ],
        }
    ]
    return chat(messages, max_tokens=2048)
