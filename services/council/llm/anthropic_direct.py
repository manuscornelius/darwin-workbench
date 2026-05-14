"""Anthropic API direct provider."""

from __future__ import annotations

import json
import os
from typing import AsyncIterator

from anthropic import AsyncAnthropic

from llm.base import LLMProvider, LLMRequest, LLMStreamEvent


class AnthropicDirectProvider(LLMProvider):
    """Talks straight to api.anthropic.com using the official SDK."""

    name = "anthropic_direct"

    def __init__(self, api_key: str | None = None) -> None:
        self._client = AsyncAnthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        def stamp(event_type: str, data: dict) -> LLMStreamEvent:
            return LLMStreamEvent(
                type=event_type,
                data=data,
                agent=request.agent,
                prompt_version=request.prompt_version,
                provider=self.name,
                model=request.model,
            )

        stream_kwargs = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": request.messages,
        }
        if request.tools:
            stream_kwargs["tools"] = request.tools
        if request.temperature is not None:
            stream_kwargs["temperature"] = request.temperature

        current_tool_id: str | None = None
        current_tool_input_json = ""

        async with self._client.messages.stream(**stream_kwargs) as stream:
            async for event in stream:
                event_type = event.type

                if event_type == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use":
                        current_tool_id = block.id
                        current_tool_input_json = ""
                        yield stamp("tool_use_start", {"id": block.id, "name": block.name})

                elif event_type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        yield stamp("text", {"text": delta.text})
                    elif delta.type == "input_json_delta" and current_tool_id:
                        current_tool_input_json += delta.partial_json
                        yield stamp("tool_use_input", {
                            "id": current_tool_id,
                            "partial_json": delta.partial_json,
                        })

                elif event_type == "content_block_stop":
                    if current_tool_id:
                        try:
                            tool_input = (
                                json.loads(current_tool_input_json)
                                if current_tool_input_json else {}
                            )
                        except json.JSONDecodeError:
                            tool_input = {}
                        yield stamp("tool_use_end", {
                            "id": current_tool_id,
                            "input": tool_input,
                        })
                        current_tool_id = None
                        current_tool_input_json = ""

            final_message = await stream.get_final_message()
            yield stamp("turn_end", {
                "stop_reason": final_message.stop_reason,
                "usage": {
                    "prompt": final_message.usage.input_tokens,
                    "completion": final_message.usage.output_tokens,
                    "cache_creation": getattr(final_message.usage, "cache_creation_input_tokens", 0) or 0,
                    "cache_read": getattr(final_message.usage, "cache_read_input_tokens", 0) or 0,
                },
                "stop_blocks": [
                    {
                        "type": b.type,
                        **({"text": b.text} if b.type == "text" else {}),
                        **({"id": b.id, "name": b.name, "input": b.input} if b.type == "tool_use" else {}),
                    }
                    for b in final_message.content
                ],
            })
