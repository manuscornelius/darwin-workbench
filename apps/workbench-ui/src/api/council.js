const COUNCIL_URL = "http://127.0.0.1:8001/chat";

export async function askCouncil(userMessage, onChunk, onAuditEvent) {
  const response = await fetch(COUNCIL_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: userMessage }),
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(err || "Council service call failed");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const data = line.slice(6).trim();
      if (!data) continue;

      try {
        const event = JSON.parse(data);

        if (event.type === "text") {
          onChunk(event.text);
        }

        if (event.type === "tool_call_start") {
          onAuditEvent({
            id: event.id,
            time: event.time,
            type: "tool_call",
            layer: "mcp",
            platform: "SAP_BPC_MS",
            tool: event.name,
            status: "pending",
            ms: null,
            startedAt: Date.now(),
            promptVersion: null,
          });
        }

        if (event.type === "tool_call_end") {
          onAuditEvent({
            type: "tool_result",
            toolUseId: event.id,
            status: event.status,
            ms: event.ms,
          });
        }

        if (event.type === "node_start") {
          onAuditEvent({ type: "node_start", node: event.node, time: event.time });
        }
        if (event.type === "node_end") {
          onAuditEvent({ type: "node_end", node: event.node, duration_ms: event.duration_ms });
        }

        if (event.type === "llm_turn_end") {
          const usage = event.usage || {};
          const tokens = (usage.prompt || 0) + (usage.completion || 0);
          if (tokens > 0) {
            onAuditEvent({ type: "token_usage", tokens });
          }
        }

        if (event.type === "prompt_loaded") {
          onAuditEvent({
            type: "prompt_loaded",
            agent: event.agent,
            version: event.version,
            source: event.source,
          });
        }

        if (event.type === "error") {
          const parts = [];
          if (event.provider_error_type) parts.push(event.provider_error_type);
          else if (event.error_type) parts.push(event.error_type);
          if (event.status_code) parts.push(`HTTP ${event.status_code}`);
          const prefix = parts.length ? `${parts.join(" · ")}: ` : "";
          throw new Error(`${prefix}${event.message || "Unknown error"}`);
        }
      } catch (err) {
        // Only swallow malformed JSON — let real errors (e.g. the structured
        // "error" SSE event) propagate up to handleSend.
        if (!(err instanceof SyntaxError)) throw err;
      }
    }
  }
}
