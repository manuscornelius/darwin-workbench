"""AC-00 acceptance test for the Darwin AI Workbench MVW.

Translates the spec's AC-00 criterion into automated assertions runnable
against the locally running stack. The AWS-specific elements (Secrets
Manager, Bedrock, 20-minute provisioning) are deferred — this test covers
the council-and-data parts of AC-00 that can be verified today on the Omen.

Preconditions when run:
  1. epm-connect MCP server on 127.0.0.1:8000
  2. council service on 127.0.0.1:8001
  3. workbench-ui Vite server on 127.0.0.1:5173 (optional — only the URL is
     reachability-checked; we don't drive the browser)

Run with:
    pytest tests/test_ac00.py -v
"""

from __future__ import annotations

import json
import time

import httpx
import pytest


COUNCIL_URL = "http://127.0.0.1:8001"
UI_URL = "http://127.0.0.1:5173"
CANONICAL_PROMPT = (
    "Connect to the BPC environment and describe the dimension structure you find"
)

# Real entities we expect synthesis to surface. The list is intentionally
# loose — we don't assert exact counts, only that real environment-level
# names appear, which proves the response is grounded in MCP data and not
# fabricated.
EXPECTED_ENVIRONMENT_NAME = "Darwin_Connect"
EXPECTED_DIMENSION_NAMES_ANY_OF = {
    "Account", "Entity", "Time", "Category", "DataSrc", "Currency", "Flow",
}

# Required preconditions inside the audit trail
REQUIRED_AUDIT_EVENT_TYPES = {
    "prompt_loaded",
    "node_start",
    "node_end",
    "tool_call",        # an MCP call started
    "tool_result",      # ...and its result
}

# MCP tools we expect extraction to invoke at minimum
MIN_REQUIRED_MCP_TOOLS = {"list_environments"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def http_client():
    """Synchronous httpx client — simpler than async for sequential checks."""
    with httpx.Client(timeout=120.0) as client:
        yield client


# ---------------------------------------------------------------------------
# AC-00.1 — services reachable
# ---------------------------------------------------------------------------

def test_ac00_01_council_health(http_client: httpx.Client) -> None:
    """The council service is up and reports its configuration."""
    response = http_client.get(f"{COUNCIL_URL}/health")
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["status"] == "ok"
    assert data["provider"] == "anthropic_direct"
    assert data["storage"] == "sqlite"
    assert data["graph_nodes"] == ["intake", "extraction", "synthesis"]

    # At least the five MCP tools we wired must be visible
    expected_tools = {
        "list_environments", "list_models", "list_dimensions",
        "get_dimension_members", "query_data",
    }
    assert expected_tools.issubset(set(data["tools"])), (
        f"Missing tools. Got: {data['tools']}"
    )


def test_ac00_02_ui_reachable(http_client: httpx.Client) -> None:
    """The Workbench UI is being served. Soft check: just confirm a 200/302."""
    try:
        response = http_client.get(UI_URL, follow_redirects=True)
    except httpx.RequestError:
        pytest.skip(f"UI dev server not running at {UI_URL}")
    assert response.status_code == 200
    assert "darwin" in response.text.lower() or "workbench" in response.text.lower(), (
        "UI response doesn't look like the workbench"
    )


# ---------------------------------------------------------------------------
# AC-00.3 — council responds to the canonical prompt
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def canonical_session(http_client: httpx.Client) -> dict:
    """Send the canonical AC-00 prompt and capture the full SSE stream.

    Returns a dict with session_id, raw events, accumulated text, and timing.
    """
    started_at = time.time()

    with http_client.stream(
        "POST",
        f"{COUNCIL_URL}/chat",
        json={"message": CANONICAL_PROMPT},
        timeout=180.0,
    ) as response:
        assert response.status_code == 200, response.read().decode()

        events: list[dict] = []
        text_chunks: list[str] = []
        session_id: str | None = None

        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = json.loads(line[6:])
            events.append(payload)

            etype = payload.get("type")
            if etype == "session_ready":
                session_id = payload["session_id"]
            elif etype == "text":
                text_chunks.append(payload["text"])
            elif etype == "error":
                pytest.fail(
                    f"Council errored: {payload.get('provider_error_type') or payload.get('error_type')}: "
                    f"{payload.get('message')}"
                )

    duration = time.time() - started_at
    return {
        "session_id": session_id,
        "events": events,
        "response_text": "".join(text_chunks),
        "duration_seconds": duration,
    }


def test_ac00_03_response_completed(canonical_session: dict) -> None:
    """The council emits a 'done' event — the run terminated cleanly."""
    event_types = [e.get("type") for e in canonical_session["events"]]
    assert "session_ready" in event_types, "No session_ready event"
    assert "done" in event_types, (
        f"Run did not complete cleanly. Events seen: {set(event_types)}"
    )


def test_ac00_04_response_grounded_in_real_data(canonical_session: dict) -> None:
    """The user-facing response must reference real BPC entities."""
    text = canonical_session["response_text"]
    assert text.strip(), "Council produced empty response"

    assert EXPECTED_ENVIRONMENT_NAME in text, (
        f"Response does not reference real environment '{EXPECTED_ENVIRONMENT_NAME}'. "
        f"First 500 chars:\n{text[:500]}"
    )

    # At least two real dimension names must appear — proves dimension data was read
    dims_in_text = {d for d in EXPECTED_DIMENSION_NAMES_ANY_OF if d in text}
    assert len(dims_in_text) >= 2, (
        f"Response references too few real dimensions. Expected at least 2 of "
        f"{EXPECTED_DIMENSION_NAMES_ANY_OF}, found {dims_in_text}.\n"
        f"First 800 chars:\n{text[:800]}"
    )


# ---------------------------------------------------------------------------
# AC-00.5 — audit trail shows MCP tool calls and prompt versions
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def session_detail(http_client: httpx.Client, canonical_session: dict) -> dict:
    """Fetch the persisted session record from the /sessions/{id} endpoint."""
    session_id = canonical_session["session_id"]
    assert session_id, "No session_id captured from canonical run"
    response = http_client.get(f"{COUNCIL_URL}/sessions/{session_id}")
    assert response.status_code == 200, response.text
    return response.json()


def test_ac00_05_audit_trail_persisted(session_detail: dict) -> None:
    """The audit log contains the required event types."""
    audit = session_detail["audit"]
    assert len(audit) > 0, "No audit events persisted"

    seen_types = {e["event_type"] for e in audit}
    missing = REQUIRED_AUDIT_EVENT_TYPES - seen_types
    assert not missing, (
        f"Required audit event types missing: {missing}. Got: {seen_types}"
    )


def test_ac00_06_audit_shows_mcp_tool_calls(session_detail: dict) -> None:
    """The audit trail names real MCP tools that were called."""
    audit = session_detail["audit"]
    tool_call_events = [e for e in audit if e["event_type"] == "tool_call"]
    assert tool_call_events, "No tool_call events in audit"

    tools_called = {e["payload"].get("tool_name") for e in tool_call_events}
    tools_called.discard(None)

    missing = MIN_REQUIRED_MCP_TOOLS - tools_called
    assert not missing, (
        f"Required MCP tools were not called: {missing}. Called: {tools_called}"
    )


def test_ac00_07_audit_shows_prompt_versions(session_detail: dict) -> None:
    """The audit trail names the prompt versions used for each LLM call."""
    audit = session_detail["audit"]

    # Every node ran a prompt_loaded event with the agent + version it used
    prompt_events = [e for e in audit if e["event_type"] == "prompt_loaded"]
    assert prompt_events, "No prompt_loaded events in audit"

    versions = {e["payload"].get("version") for e in prompt_events}
    versions.discard(None)
    assert versions, "prompt_loaded events lack version data"

    # All three council nodes must appear
    agents = {e["payload"].get("agent") for e in prompt_events}
    assert {"intake", "extraction", "synthesis"}.issubset(agents), (
        f"Not all council node prompts were recorded. Got agents: {agents}"
    )

    # Versions should look like 'name@x.y.z' — one per agent at minimum
    for v in versions:
        assert "@" in v, f"Prompt version doesn't look versioned: {v}"


def test_ac00_08_tool_calls_persisted_with_outputs(session_detail: dict) -> None:
    """First-class ToolCall rows exist with inputs, outputs and durations."""
    tool_calls = session_detail["tool_calls"]
    assert tool_calls, "No ToolCall rows persisted"

    for tc in tool_calls:
        assert tc["tool_call_id"], "tool_call_id missing"
        assert tc["tool_name"], "tool_name missing"
        assert tc["input"] is not None, f"input missing for {tc['tool_name']}"
        # output may be None for tool calls completed before the graph
        # backfill, so this is a soft check — we want at least one with output
    populated = [tc for tc in tool_calls if tc.get("output")]
    assert populated, "No ToolCall row has a persisted output payload"


def test_ac00_09_messages_persisted(session_detail: dict) -> None:
    """Both the user message and the assistant response are persisted."""
    messages = session_detail["messages"]
    assert len(messages) >= 2, f"Expected at least 2 messages, got {len(messages)}"

    user_msgs = [m for m in messages if m["role"] == "user"]
    asst_msgs = [m for m in messages if m["role"] == "assistant"]

    assert user_msgs, "No user message persisted"
    assert asst_msgs, "No assistant message persisted"

    # User message should contain the canonical prompt verbatim
    user_text = " ".join(
        b.get("text", "") for m in user_msgs for b in m["content"]
    )
    assert CANONICAL_PROMPT in user_text


# ---------------------------------------------------------------------------
# AC-00 summary — emits a structured pass/fail report
# ---------------------------------------------------------------------------

def test_ac00_summary(canonical_session: dict, session_detail: dict) -> None:
    """Print a human-readable AC-00 report. Always passes — this is reporting."""
    print()
    print("=" * 72)
    print("AC-00 SUMMARY")
    print("=" * 72)
    print(f"Session ID:          {canonical_session['session_id']}")
    print(f"Duration:            {canonical_session['duration_seconds']:.1f}s")
    print(f"Response chars:      {len(canonical_session['response_text'])}")
    print(f"Audit events:        {len(session_detail['audit'])}")
    print(f"Tool calls:          {len(session_detail['tool_calls'])}")
    print(f"Messages persisted:  {len(session_detail['messages'])}")
    print()

    tool_calls = session_detail["tool_calls"]
    if tool_calls:
        tool_names = sorted({tc["tool_name"] for tc in tool_calls})
        print(f"MCP tools called:    {', '.join(tool_names)}")

    audit = session_detail["audit"]
    prompt_events = [e for e in audit if e["event_type"] == "prompt_loaded"]
    versions = sorted({e["payload"].get("version") for e in prompt_events if e["payload"].get("version")})
    if versions:
        print(f"Prompt versions:     {', '.join(versions)}")

    print("=" * 72)
