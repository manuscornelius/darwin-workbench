"""AWS Bedrock provider — wraps boto3 bedrock-runtime with streaming.

Uses the Converse API (recommended over InvokeModel for tool use and
multi-turn conversations). Credentials come from the standard AWS credential
chain: ~/.aws/credentials (set by aws configure), environment variables, or
IAM role when running on AWS compute.

Model ID defaults to the cross-region inference profile for Claude Sonnet 4.6
in us-east-1, which gives the best availability and burst handling.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, AsyncIterator

import boto3
from botocore.config import Config

from llm.base import LLMProvider, LLMRequest, LLMStreamEvent


_DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-6-v1"
_DEFAULT_REGION = "us-east-1"


def _anthropic_tool_to_bedrock(tool: dict[str, Any]) -> dict[str, Any]:
    """Convert Anthropic-format tool definition to Bedrock Converse format."""
    return {
        "toolSpec": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "inputSchema": {
                "json": tool.get("input_schema", {"type": "object", "properties": {}})
            },
        }
    }


def _anthropic_messages_to_bedrock(
    messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Convert Anthropic-format messages to Bedrock Converse format."""
    bedrock_messages = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        # Content can be a plain string or a list of blocks
        if isinstance(content, str):
            bedrock_messages.append({
                "role": role,
                "content": [{"text": content}],
            })
            continue

        bedrock_content = []
        for block in content:
            btype = block.get("type")
            if btype == "text":
                bedrock_content.append({"text": block["text"]})
            elif btype == "tool_use":
                bedrock_content.append({
                    "toolUse": {
                        "toolUseId": block["id"],
                        "name": block["name"],
                        "input": block.get("input", {}),
                    }
                })
            elif btype == "tool_result":
                # Flatten content list to text for Bedrock
                result_content = block.get("content", [])
                if isinstance(result_content, list):
                    text = " ".join(
                        c.get("text", "") for c in result_content
                        if isinstance(c, dict)
                    )
                else:
                    text = str(result_content)
                bedrock_content.append({
                    "toolResult": {
                        "toolUseId": block["tool_use_id"],
                        "content": [{"text": text}],
                        "status": "error" if block.get("is_error") else "success",
                    }
                })

        if bedrock_content:
            bedrock_messages.append({"role": role, "content": bedrock_content})

    return bedrock_messages


class BedrockProvider(LLMProvider):
    """AWS Bedrock provider using the Converse streaming API."""

    name = "bedrock"

    def __init__(
        self,
        model_id: str | None = None,
        region: str | None = None,
    ) -> None:
        self._model_id = (
            model_id
            or os.getenv("BEDROCK_MODEL_ID", _DEFAULT_MODEL)
        )
        self._region = region or os.getenv("AWS_REGION", _DEFAULT_REGION)
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=self._region,
            config=Config(
                retries={"max_attempts": 3, "mode": "adaptive"},
                read_timeout=300,
            ),
        )

    def stamp(
        self, event_type: str, data: dict, request: LLMRequest
    ) -> LLMStreamEvent:
        return LLMStreamEvent(
            type=event_type,
            data=data,
            agent=request.agent,
            prompt_version=request.prompt_version,
            provider=self.name,
            model=self._model_id,
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        """Stream one LLM turn via Bedrock Converse streaming API.

        boto3 streaming is synchronous under the hood — we run it in the
        current thread since FastAPI/uvicorn handles the async boundary.
        The call blocks only during the actual HTTP read, which is fine for
        our single-process local dev setup. For production on AWS compute,
        wrap in asyncio.to_thread().
        """
        bedrock_messages = _anthropic_messages_to_bedrock(request.messages)

        kwargs: dict[str, Any] = {
            "modelId": self._model_id,
            "system": [{"text": request.system}],
            "messages": bedrock_messages,
            "inferenceConfig": {
                "maxTokens": request.max_tokens,
            },
        }

        if request.tools:
            kwargs["toolConfig"] = {
                "tools": [_anthropic_tool_to_bedrock(t) for t in request.tools]
            }

        if request.temperature is not None:
            kwargs["inferenceConfig"]["temperature"] = request.temperature

        response = self._client.converse_stream(**kwargs)
        stream = response.get("stream")

        current_tool_id: str | None = None
        current_tool_name: str | None = None
        current_tool_input_json = ""
        stop_reason = "end_turn"
        usage: dict[str, Any] = {}
        stop_blocks: list[dict[str, Any]] = []
        text_so_far = ""

        for chunk in stream:
            # --- Text delta
            if "contentBlockDelta" in chunk:
                delta = chunk["contentBlockDelta"].get("delta", {})
                if "text" in delta:
                    text_so_far += delta["text"]
                    yield self.stamp("text", {"text": delta["text"]}, request)
                elif "toolUse" in delta:
                    current_tool_input_json += delta["toolUse"].get("input", "")

            # --- Block start
            elif "contentBlockStart" in chunk:
                start = chunk["contentBlockStart"].get("start", {})
                if "toolUse" in start:
                    tool = start["toolUse"]
                    current_tool_id = tool["toolUseId"]
                    current_tool_name = tool["name"]
                    current_tool_input_json = ""
                    yield self.stamp("tool_use_start", {
                        "id": current_tool_id,
                        "name": current_tool_name,
                    }, request)

            # --- Block stop
            elif "contentBlockStop" in chunk:
                if current_tool_id:
                    try:
                        tool_input = (
                            json.loads(current_tool_input_json)
                            if current_tool_input_json else {}
                        )
                    except json.JSONDecodeError:
                        tool_input = {}
                    yield self.stamp("tool_use_end", {
                        "id": current_tool_id,
                        "input": tool_input,
                    }, request)
                    stop_blocks.append({
                        "type": "tool_use",
                        "id": current_tool_id,
                        "name": current_tool_name,
                        "input": tool_input,
                    })
                    current_tool_id = None
                    current_tool_name = None
                    current_tool_input_json = ""
                elif text_so_far:
                    stop_blocks.append({"type": "text", "text": text_so_far})
                    text_so_far = ""

            # --- Message stop
            elif "messageStop" in chunk:
                stop_reason_raw = chunk["messageStop"].get("stopReason", "end_turn")
                # Bedrock uses tool_use, end_turn, max_tokens — same as Anthropic
                stop_reason = stop_reason_raw

            # --- Usage metadata
            elif "metadata" in chunk:
                meta = chunk["metadata"]
                if "usage" in meta:
                    u = meta["usage"]
                    usage = {
                        "prompt": u.get("inputTokens", 0),
                        "completion": u.get("outputTokens", 0),
                        "cache_creation": 0,
                        "cache_read": 0,
                    }

        yield self.stamp("turn_end", {
            "stop_reason": stop_reason,
            "usage": usage,
            "stop_blocks": stop_blocks,
        }, request)
