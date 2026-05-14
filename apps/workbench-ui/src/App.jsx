import React, { useState, useRef, useEffect } from "react";
import { askCouncil } from "./api/council";
import { listSessions, getSession } from "./api/sessions";

const COLORS = {
  bg: "#F8F7F4",
  surface: "#FFFFFF",
  surfaceAlt: "#F2F1EE",
  border: "#E4E2DC",
  borderStrong: "#C8C5BC",
  text: "#1A1916",
  textMuted: "#6B6860",
  textFaint: "#A8A59E",
  accent: "#1B4F72",
  accentLight: "#EBF2F8",
  accentMid: "#2E86C1",
  green: "#1A7A4A",
  greenLight: "#E8F5EE",
  amber: "#B7770D",
  amberLight: "#FDF3DC",
  red: "#C0392B",
  redLight: "#FDECEA",
  purple: "#6B3FA0",
  purpleLight: "#F0EAF8",
};

function Tag({ children, color = "default", size = "sm" }) {
  const colors = {
    default: { bg: COLORS.surfaceAlt, text: COLORS.textMuted, border: COLORS.border },
    blue: { bg: COLORS.accentLight, text: COLORS.accent, border: "#C5D9EC" },
    green: { bg: COLORS.greenLight, text: COLORS.green, border: "#C0E0CE" },
    amber: { bg: COLORS.amberLight, text: COLORS.amber, border: "#EDD9A3" },
    red: { bg: COLORS.redLight, text: COLORS.red, border: "#F0C0BB" },
    purple: { bg: COLORS.purpleLight, text: COLORS.purple, border: "#D5C2EC" },
  };
  const c = colors[color] || colors.default;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", padding: size === "xs" ? "1px 6px" : "2px 8px", borderRadius: 4, fontSize: size === "xs" ? 10 : 11, fontWeight: 600, letterSpacing: "0.03em", textTransform: "uppercase", background: c.bg, color: c.text, border: `1px solid ${c.border}`, whiteSpace: "nowrap" }}>
      {children}
    </span>
  );
}

function AuditEvent({ event, visible }) {
  // token_usage events feed the status-bar counter only — no row in the trail.
  if (event.type === "token_usage") return null;
  const typeConfig = { tool_call: { color: "blue", label: "MCP" }, bedrock: { color: "purple", label: "LLM" } };
  const cfg = typeConfig[event.type] || { color: "default", label: "EVT" };
  return (
    <div style={{ padding: "10px 14px", borderBottom: `1px solid ${COLORS.border}`, opacity: visible ? 1 : 0, transform: visible ? "translateY(0)" : "translateY(6px)", transition: "opacity 0.3s ease, transform 0.3s ease", background: COLORS.surface }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
        <Tag color={cfg.color} size="xs">{cfg.label}</Tag>
        {event.type === "tool_call" && (<><span style={{ fontSize: 12, fontWeight: 600, color: COLORS.text, fontFamily: "'DM Mono', monospace" }}>{event.tool}</span><Tag color="default" size="xs">{event.platform}</Tag></>)}
        {event.type === "bedrock" && (<><span style={{ fontSize: 12, fontWeight: 600, color: COLORS.text }}>{event.agent}</span>{event.tokens?.cacheHit && <Tag color="green" size="xs">cache hit</Tag>}</>)}
        <Tag color={event.status === "success" ? "green" : "red"} size="xs">{event.status}</Tag>
        {event.ms && <span style={{ marginLeft: "auto", fontSize: 11, color: COLORS.textFaint, fontFamily: "'DM Mono', monospace" }}>{event.ms}ms</span>}
      </div>
      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <span style={{ fontSize: 11, color: COLORS.textFaint, fontFamily: "'DM Mono', monospace" }}>{event.time}</span>
        {event.promptVersion && (<span style={{ fontSize: 11, color: COLORS.textMuted }}>prompt: <span style={{ fontFamily: "'DM Mono', monospace", color: COLORS.purple }}>{event.promptVersion}</span></span>)}
        {event.tokens && (<span style={{ fontSize: 11, color: COLORS.textMuted }}>{event.tokens.prompt.toLocaleString()} + {event.tokens.completion.toLocaleString()} tokens</span>)}
      </div>
    </div>
  );
}

function MessageBubble({ message }) {
  const isUser = message.role === "user";
  const renderContent = (content) => {
    const lines = content.split("\n");
    const elements = [];
    let tableBuffer = [];
    let inTable = false;
    let key = 0;
    const flushTable = () => {
      if (tableBuffer.length < 2) { tableBuffer.forEach(l => elements.push(<p key={key++} style={{ margin: "4px 0", fontSize: 14, color: COLORS.text, lineHeight: 1.6 }}>{l}</p>)); tableBuffer = []; return; }
      const headers = tableBuffer[0].split("|").map(h => h.trim()).filter(Boolean);
      const rows = tableBuffer.slice(2).map(r => r.split("|").map(c => c.trim()).filter(Boolean));
      elements.push(
        <div key={key++} style={{ overflowX: "auto", margin: "12px 0" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead><tr style={{ background: COLORS.surfaceAlt }}>{headers.map((h, i) => (<th key={i} style={{ padding: "7px 12px", textAlign: "left", fontWeight: 600, color: COLORS.textMuted, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.04em", borderBottom: `2px solid ${COLORS.border}`, whiteSpace: "nowrap" }}>{h}</th>))}</tr></thead>
            <tbody>{rows.map((row, i) => (<tr key={i} style={{ borderBottom: `1px solid ${COLORS.border}` }}>{row.map((cell, j) => (<td key={j} style={{ padding: "7px 12px", color: COLORS.text, fontFamily: j > 0 ? "'DM Mono', monospace" : "inherit", fontSize: j > 0 ? 13 : 14 }}>{cell}</td>))}</tr>))}</tbody>
          </table>
        </div>
      );
      tableBuffer = [];
    };
    for (const line of lines) {
      if (line.startsWith("|")) { inTable = true; tableBuffer.push(line); continue; }
      if (inTable) { flushTable(); inTable = false; }
      if (line.startsWith("**") && line.endsWith("**") && line.length > 4) {
        elements.push(<p key={key++} style={{ margin: "14px 0 6px", fontSize: 14, fontWeight: 700, color: COLORS.text }}>{line.slice(2, -2)}</p>);
      } else if (line.startsWith("- ")) {
        const parts = line.slice(2).split(/\*\*(.*?)\*\*/);
        elements.push(<div key={key++} style={{ display: "flex", gap: 8, margin: "3px 0", fontSize: 14, color: COLORS.text, lineHeight: 1.6 }}><span style={{ color: COLORS.accent, marginTop: 2, flexShrink: 0 }}>·</span><span>{parts.map((p, i) => i % 2 === 1 ? <strong key={i}>{p}</strong> : p)}</span></div>);
      } else if (line === "---") {
        elements.push(<hr key={key++} style={{ border: "none", borderTop: `1px solid ${COLORS.border}`, margin: "12px 0" }} />);
      } else if (line.trim()) {
        const parts = line.split(/\*\*(.*?)\*\*/);
        elements.push(<p key={key++} style={{ margin: "4px 0", fontSize: 14, color: COLORS.text, lineHeight: 1.65 }}>{parts.map((p, i) => i % 2 === 1 ? <strong key={i}>{p}</strong> : p)}</p>);
      }
    }
    if (inTable) flushTable();
    return elements;
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: isUser ? "flex-end" : "flex-start", marginBottom: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        {!isUser && (<div style={{ width: 22, height: 22, borderRadius: 6, background: COLORS.accent, display: "flex", alignItems: "center", justifyContent: "center" }}><span style={{ fontSize: 11, color: "#fff", fontWeight: 700 }}>D</span></div>)}
        <span style={{ fontSize: 11, fontWeight: 600, color: COLORS.textMuted, textTransform: "uppercase", letterSpacing: "0.05em" }}>{isUser ? "You" : "Darwin Council"}</span>
      </div>
      <div style={{ maxWidth: "92%", padding: isUser ? "10px 14px" : "14px 18px", borderRadius: isUser ? "12px 12px 4px 12px" : "4px 12px 12px 12px", background: isUser ? COLORS.accent : COLORS.surface, border: isUser ? "none" : `1px solid ${COLORS.border}`, color: isUser ? "#fff" : COLORS.text, boxShadow: isUser ? "none" : "0 1px 3px rgba(0,0,0,0.06)" }}>
        {isUser ? <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6 }}>{message.content}</p> : renderContent(message.content)}
      </div>
    </div>
  );
}

function StatusBar({ connected, mcpCalls, totalTokens }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "6px 16px", background: COLORS.surfaceAlt, borderTop: `1px solid ${COLORS.border}`, fontSize: 11 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
        <div style={{ width: 6, height: 6, borderRadius: "50%", background: connected ? COLORS.green : COLORS.red }} />
        <span style={{ color: COLORS.textMuted, fontWeight: 600 }}>{connected ? "Darwin_Connect" : "Disconnected"}</span>
      </div>
      <span style={{ color: COLORS.borderStrong }}>|</span>
      <span style={{ color: COLORS.textFaint }}><span style={{ fontFamily: "'DM Mono', monospace", color: COLORS.textMuted }}>{mcpCalls}</span> MCP calls</span>
      <span style={{ color: COLORS.borderStrong }}>|</span>
      <span style={{ color: COLORS.textFaint }}><span style={{ fontFamily: "'DM Mono', monospace", color: COLORS.textMuted }}>{totalTokens.toLocaleString()}</span> tokens</span>
      <span style={{ color: COLORS.borderStrong }}>|</span>
      <span style={{ color: COLORS.textFaint }}>SAP_BPC_MS · lifeline22.column5.cloud</span>
      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
        <Tag color="green" size="xs">MVW</Tag>
        <span style={{ color: COLORS.textFaint }}>v0.1.0</span>
      </div>
    </div>
  );
}

export default function DarwinWorkbench() {
  const [messages, setMessages] = useState([]);
  const [auditEvents, setAuditEvents] = useState([]);
  const [visibleEvents, setVisibleEvents] = useState(new Set());
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeTab, setActiveTab] = useState("audit");
  const [streamingText, setStreamingText] = useState("");
  const [error, setError] = useState(null);
  const [activeNode, setActiveNode] = useState(null);
  const [completedNodes, setCompletedNodes] = useState(new Set());
  const [sessions, setSessions] = useState([]);
  const [activeSessions, setActiveSessionId] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const messagesEndRef = useRef(null);
  const auditEndRef = useRef(null);
  const textareaRef = useRef(null);

  const loadSessions = async () => {
    try {
      const data = await listSessions();
      setSessions(data);
    } catch (err) {
      console.error("Failed to load sessions:", err);
    }
  };

  useEffect(() => { loadSessions(); }, []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    auditEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const handleSend = async () => {
    const userMsg = input.trim();
    if (!userMsg || isStreaming) return;

    setInput("");
    setIsStreaming(true);
    setError(null);
    setActiveNode(null);
    setCompletedNodes(new Set());
    setMessages(prev => [...prev, { role: "user", content: userMsg }]);
    setTimeout(scrollToBottom, 50);

    let fullResponse = "";

    try {
      await askCouncil(
        userMsg,
        // onChunk — called for each streamed text delta
        (chunk) => {
          fullResponse += chunk;
          setStreamingText(fullResponse);
          setTimeout(scrollToBottom, 10);
        },
        // onAuditEvent — match tool_result to the original tool_call by blockIndex
        (event) => {
          if (event.type === "node_start") {
            setActiveNode(event.node);
            setAuditEvents(prev => [...prev, event]);
            return;
          }
          if (event.type === "node_end") {
            setActiveNode(null);
            setCompletedNodes(prev => new Set([...prev, event.node]));
            setAuditEvents(prev => [...prev, event]);
            return;
          }
          if (event.type === "prompt_loaded") {
            setAuditEvents(prev => [...prev, event]);
            return;
          }

          if (event.type === "token_usage") {
            // Counter-only — skip visibility tracking (no id, no row).
            setAuditEvents(prev => [...prev, event]);
            return;
          }

          if (event.type === "tool_result") {
            // Update the matching tool_call row instead of adding a new one.
            // Match by toolUseId (call.id === result.tool_use_id), fall back to blockIndex.
            setAuditEvents(prev => prev.map(e => {
              if (e.type === "tool_call" && e.id === event.toolUseId && e.status === "pending") {
                return {
                  ...e,
                  status: event.status,
                  ms: event.ms ?? (e.startedAt ? Date.now() - e.startedAt : null),
                };
              }
              return e;
            }));
            setTimeout(scrollToBottom, 10);
            return;
          }

          // tool_call — add new row as before
          setAuditEvents(prev => {
            const updated = [...prev, event];
            setVisibleEvents(v => new Set([...v, event.id]));
            return updated;
          });
          setTimeout(scrollToBottom, 10);
        }
      );

      // Streaming complete — move to messages
      setStreamingText("");
      setMessages(prev => [...prev, { role: "assistant", content: fullResponse }]);
      loadSessions();
    } catch (err) {
      setStreamingText("");
      setError(err.message);
    } finally {
      setIsStreaming(false);
      setTimeout(scrollToBottom, 50);
    }
  };

  const handleLoadSession = async (sessionId) => {
    try {
      const data = await getSession(sessionId);
      setActiveSessionId(sessionId);
      const restored = [];
      for (const msg of data.messages) {
        if (msg.role === "user") {
          const text = msg.content.find(b => b.type === "text")?.text || "";
          if (text) restored.push({ role: "user", content: text });
        } else if (msg.role === "assistant") {
          const text = msg.content.find(b => b.type === "text")?.text || "";
          if (text) restored.push({ role: "assistant", content: text });
        }
      }
      setMessages(restored);
      setAuditEvents([]);
      setVisibleEvents(new Set());
      setError(null);
      setActiveNode(null);
      setCompletedNodes(new Set());
      setTimeout(scrollToBottom, 50);
    } catch (err) {
      console.error("Failed to load session:", err);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  const handleSuggestion = (text) => {
    setInput(text);
    textareaRef.current?.focus();
  };

  const mcpCalls = auditEvents.filter(e => e.type === "tool_call").length;
  const totalTokens = auditEvents
    .filter(e => e.type === "token_usage")
    .reduce((sum, e) => sum + e.tokens, 0);
  // Prompt versions come from explicit prompt_loaded events. Dedupe by versioned id.
  const promptVersions = (() => {
    const seen = new Map();
    for (const e of auditEvents) {
      if (e.type === "prompt_loaded" && !seen.has(e.version)) {
        seen.set(e.version, { agent: e.agent, version: e.version, source: e.source });
      }
    }
    return Array.from(seen.values());
  })();

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column", background: COLORS.bg, fontFamily: "'DM Sans', system-ui, sans-serif" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", padding: "0 20px", height: 52, background: COLORS.surface, borderBottom: `1px solid ${COLORS.border}`, flexShrink: 0, boxShadow: "0 1px 0 rgba(0,0,0,0.04)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 28, height: 28, borderRadius: 8, background: COLORS.accent, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <span style={{ fontSize: 13, fontWeight: 800, color: "#fff", letterSpacing: "-0.03em" }}>D</span>
          </div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: COLORS.text, letterSpacing: "-0.02em" }}>Darwin AI Workbench</div>
            <div style={{ fontSize: 10, color: COLORS.textFaint, marginTop: -1 }}>Minimal Viable Workstation</div>
          </div>
        </div>
        <button onClick={() => setSidebarOpen(s => !s)} style={{ width: 28, height: 28, borderRadius: 6, border: `1px solid ${COLORS.border}`, background: sidebarOpen ? COLORS.accentLight : "transparent", color: sidebarOpen ? COLORS.accent : COLORS.textMuted, cursor: "pointer", fontSize: 14, display: "flex", alignItems: "center", justifyContent: "center", marginLeft: 12 }}>☰</button>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: 32 }}>
          {["Council", "Pipelines", "Knowledge", "Control Room"].map((tab, i) => (
            <button key={tab} style={{ padding: "4px 12px", borderRadius: 6, border: "none", background: i === 0 ? COLORS.accentLight : "transparent", color: i === 0 ? COLORS.accent : COLORS.textMuted, fontSize: 12, fontWeight: i === 0 ? 700 : 500, cursor: "pointer", opacity: i > 0 ? 0.5 : 1 }}>
              {tab}{i > 0 && <span style={{ marginLeft: 4, fontSize: 9, color: COLORS.textFaint }}>Phase 1</span>}
            </button>
          ))}
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ fontSize: 12, color: COLORS.textMuted }}><span style={{ fontWeight: 600 }}>Manus</span><span style={{ color: COLORS.textFaint }}> · Column5</span></div>
          <div style={{ width: 28, height: 28, borderRadius: "50%", background: COLORS.accent, display: "flex", alignItems: "center", justifyContent: "center" }}><span style={{ fontSize: 11, fontWeight: 700, color: "#fff" }}>M</span></div>
        </div>
      </div>

      {/* Main */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* Session sidebar */}
        {sidebarOpen && (
          <div style={{ width: 240, display: "flex", flexDirection: "column", background: COLORS.surface, borderRight: `1px solid ${COLORS.border}`, flexShrink: 0, overflow: "hidden" }}>
            <div style={{ padding: "12px 14px 8px", display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: `1px solid ${COLORS.border}` }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: COLORS.textMuted, textTransform: "uppercase", letterSpacing: "0.05em" }}>Sessions</span>
              <button onClick={() => { setMessages([]); setAuditEvents([]); setVisibleEvents(new Set()); setActiveSessionId(null); setError(null); setActiveNode(null); setCompletedNodes(new Set()); }} style={{ fontSize: 10, padding: "2px 8px", borderRadius: 5, border: `1px solid ${COLORS.border}`, background: COLORS.accentLight, color: COLORS.accent, cursor: "pointer", fontWeight: 600, fontFamily: "inherit" }}>+ New</button>
            </div>
            <div style={{ flex: 1, overflowY: "auto", padding: "6px 0" }}>
              {sessions.length === 0 ? (
                <div style={{ padding: "16px 14px", fontSize: 11, color: COLORS.textFaint, textAlign: "center" }}>No sessions yet</div>
              ) : (
                sessions.map(session => {
                  const isActive = activeSessions === session.session_id;
                  const date = new Date(session.created_at);
                  const dateStr = date.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
                  const timeStr = date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
                  return (
                    <div key={session.session_id} onClick={() => handleLoadSession(session.session_id)} style={{ padding: "8px 14px", cursor: "pointer", background: isActive ? COLORS.accentLight : "transparent", borderLeft: `3px solid ${isActive ? COLORS.accent : "transparent"}`, transition: "all 0.15s" }}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: isActive ? COLORS.accent : COLORS.text, lineHeight: 1.3, marginBottom: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {session.title || "Untitled session"}
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span style={{ fontSize: 10, color: COLORS.textFaint }}>{dateStr} {timeStr}</span>
                        <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3, background: session.status === "completed" ? COLORS.greenLight : COLORS.amberLight, color: session.status === "completed" ? COLORS.green : COLORS.amber, fontWeight: 600, textTransform: "uppercase" }}>{session.status}</span>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}
        {/* Conversation */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
          <div style={{ padding: "10px 20px", borderBottom: `1px solid ${COLORS.border}`, background: COLORS.surface, display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text }}>New Session</div>
              <div style={{ fontSize: 11, color: COLORS.textFaint }}>SAP BPC MS · Darwin_Connect · Planning</div>
            </div>
            <Tag color="blue">SAP_BPC_MS</Tag>
            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
              {["intake", "extraction", "synthesis"].map((node, i) => {
                const isActive = activeNode === node;
                const isDone = completedNodes.has(node);
                return (
                  <React.Fragment key={node}>
                    {i > 0 && <span style={{ fontSize: 10, color: COLORS.textFaint }}>→</span>}
                    <span style={{
                      padding: "2px 8px", borderRadius: 10, fontSize: 10, fontWeight: 600,
                      textTransform: "capitalize", letterSpacing: "0.03em",
                      background: isDone ? COLORS.greenLight : isActive ? COLORS.accentLight : COLORS.surfaceAlt,
                      color: isDone ? COLORS.green : isActive ? COLORS.accent : COLORS.textFaint,
                      border: `1px solid ${isDone ? "#C0E0CE" : isActive ? "#C5D9EC" : COLORS.border}`,
                      transition: "all 0.2s ease",
                    }}>
                      {isDone ? "✓ " : isActive ? "● " : "○ "}{node}
                    </span>
                  </React.Fragment>
                );
              })}
            </div>
            {isStreaming && (
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{ display: "flex", gap: 3 }}>
                  {[0, 1, 2].map(i => (<div key={i} style={{ width: 4, height: 4, borderRadius: "50%", background: COLORS.accent, animation: `bounce 1s ease-in-out ${i * 0.15}s infinite` }} />))}
                </div>
                <span style={{ fontSize: 11, color: COLORS.accent, fontWeight: 600 }}>Council thinking…</span>
              </div>
            )}
          </div>

          <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
            {messages.length === 0 && !isStreaming && (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 12 }}>
                <div style={{ width: 48, height: 48, borderRadius: 14, background: COLORS.accentLight, display: "flex", alignItems: "center", justifyContent: "center", border: `2px solid ${COLORS.accent}20` }}>
                  <span style={{ fontSize: 22 }}>🧠</span>
                </div>
                <div style={{ textAlign: "center" }}>
                  <div style={{ fontSize: 15, fontWeight: 600, color: COLORS.text, marginBottom: 4 }}>Darwin Council</div>
                  <div style={{ fontSize: 13, color: COLORS.textMuted, maxWidth: 320, lineHeight: 1.5 }}>Ask a question about your EPM environment. The council will read live data via MCP and respond.</div>
                </div>
              </div>
            )}

            {messages.map((msg, i) => <MessageBubble key={i} message={msg} />)}

            {isStreaming && streamingText && (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", marginBottom: 20 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <div style={{ width: 22, height: 22, borderRadius: 6, background: COLORS.accent, display: "flex", alignItems: "center", justifyContent: "center" }}><span style={{ fontSize: 11, color: "#fff", fontWeight: 700 }}>D</span></div>
                  <span style={{ fontSize: 11, fontWeight: 600, color: COLORS.textMuted, textTransform: "uppercase", letterSpacing: "0.05em" }}>Darwin Council</span>
                </div>
                <div style={{ maxWidth: "92%", padding: "14px 18px", borderRadius: "4px 12px 12px 12px", background: COLORS.surface, border: `1px solid ${COLORS.border}`, boxShadow: "0 1px 3px rgba(0,0,0,0.06)" }}>
                  <p style={{ margin: 0, fontSize: 14, color: COLORS.text, lineHeight: 1.65, whiteSpace: "pre-wrap" }}>
                    {streamingText}
                    <span style={{ display: "inline-block", width: 2, height: 14, background: COLORS.accent, marginLeft: 2, verticalAlign: "text-bottom", animation: "blink 1s step-end infinite" }} />
                  </p>
                </div>
              </div>
            )}

            {error && (
              <div style={{ margin: "12px 0", padding: "12px 16px", borderRadius: 8, background: COLORS.redLight, border: `1px solid ${COLORS.red}30`, fontSize: 13, color: COLORS.red }}>
                <strong>Error:</strong> {error}
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div style={{ padding: "12px 20px", background: COLORS.surface, borderTop: `1px solid ${COLORS.border}`, flexShrink: 0 }}>
            <div style={{ display: "flex", gap: 10, alignItems: "flex-end", background: COLORS.bg, border: `1.5px solid ${COLORS.border}`, borderRadius: 10, padding: "10px 12px" }}>
              <textarea ref={textareaRef} value={input} onChange={e => setInput(e.target.value)} onKeyDown={handleKeyDown} placeholder="Ask the Darwin Council anything about your EPM environment…" disabled={isStreaming} style={{ flex: 1, border: "none", background: "transparent", resize: "none", outline: "none", fontSize: 13, color: COLORS.text, fontFamily: "inherit", lineHeight: 1.5, minHeight: 40, maxHeight: 120, overflowY: "auto" }} rows={1} />
              <button onClick={handleSend} disabled={isStreaming || !input.trim()} style={{ width: 34, height: 34, borderRadius: 8, border: "none", background: isStreaming || !input.trim() ? COLORS.borderStrong : COLORS.accent, color: "#fff", cursor: isStreaming || !input.trim() ? "not-allowed" : "pointer", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, fontSize: 14, transition: "background 0.15s" }}>
                {isStreaming ? <div style={{ width: 12, height: 12, border: "2px solid rgba(255,255,255,0.4)", borderTop: "2px solid #fff", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} /> : "↑"}
              </button>
            </div>
            <div style={{ marginTop: 6, display: "flex", gap: 6 }}>
              {["Describe the dimension structure", "List all models", "Show account hierarchy"].map(s => (
                <button key={s} onClick={() => handleSuggestion(s)} style={{ padding: "3px 10px", borderRadius: 5, border: `1px solid ${COLORS.border}`, background: "transparent", color: COLORS.textMuted, fontSize: 11, cursor: "pointer", fontFamily: "inherit" }}>{s}</button>
              ))}
            </div>
          </div>

          <StatusBar connected={true} mcpCalls={mcpCalls} totalTokens={totalTokens} />
        </div>

        <div style={{ width: 1, background: COLORS.border, flexShrink: 0 }} />

        {/* Right panel */}
        <div style={{ width: 380, display: "flex", flexDirection: "column", background: COLORS.surface, flexShrink: 0 }}>
          <div style={{ display: "flex", borderBottom: `1px solid ${COLORS.border}`, padding: "0 4px", flexShrink: 0 }}>
            {["audit", "prompts"].map(tab => (
              <button key={tab} onClick={() => setActiveTab(tab)} style={{ padding: "12px 16px", border: "none", background: "transparent", fontSize: 12, fontWeight: 600, color: activeTab === tab ? COLORS.accent : COLORS.textMuted, cursor: "pointer", borderBottom: `2px solid ${activeTab === tab ? COLORS.accent : "transparent"}`, marginBottom: -1, fontFamily: "inherit", textTransform: "capitalize", letterSpacing: "0.02em" }}>
                {tab === "audit" ? "Audit Trail" : "Prompt Versions"}
                {tab === "audit" && auditEvents.length > 0 && (<span style={{ marginLeft: 6, padding: "1px 6px", borderRadius: 10, background: COLORS.accentLight, color: COLORS.accent, fontSize: 10, fontWeight: 700 }}>{auditEvents.length}</span>)}
              </button>
            ))}
          </div>

          <div style={{ flex: 1, overflowY: "auto" }}>
            {activeTab === "audit" && (
              <>
                {auditEvents.length === 0 ? (
                  <div style={{ padding: 24, textAlign: "center" }}>
                    <div style={{ fontSize: 20, marginBottom: 8 }}>📋</div>
                    <div style={{ fontSize: 12, color: COLORS.textFaint, lineHeight: 1.5 }}>MCP tool calls will appear here in real time as the council works</div>
                  </div>
                ) : (
                  <>
                    <div style={{ padding: "8px 14px", background: COLORS.surfaceAlt, borderBottom: `1px solid ${COLORS.border}`, display: "flex", gap: 12, fontSize: 11 }}>
                      <span style={{ color: COLORS.textMuted }}><span style={{ fontFamily: "'DM Mono', monospace", fontWeight: 700, color: COLORS.text }}>{mcpCalls}</span> MCP calls</span>
                      <span style={{ color: COLORS.textMuted }}><span style={{ fontFamily: "'DM Mono', monospace", fontWeight: 700, color: COLORS.text }}>{(() => { const n = auditEvents.filter(e => e.type === "tool_call" && e.status === "success").length; return `${n} tool result${n === 1 ? "" : "s"}`; })()}</span></span>
                      <span style={{ color: COLORS.textMuted }}><span style={{ fontFamily: "'DM Mono', monospace", fontWeight: 700, color: COLORS.text }}>{totalTokens.toLocaleString()}</span> tokens</span>
                    </div>
                    {auditEvents.map(event => <AuditEvent key={event.id} event={event} visible={visibleEvents.has(event.id)} />)}
                  </>
                )}
                <div ref={auditEndRef} />
              </>
            )}
            {activeTab === "prompts" && (
              <div style={{ padding: 16 }}>
                {promptVersions.length === 0 ? (
                  <div style={{ textAlign: "center", padding: 24 }}>
                    <div style={{ fontSize: 20, marginBottom: 8 }}>📄</div>
                    <div style={{ fontSize: 12, color: COLORS.textFaint, lineHeight: 1.5 }}>Prompt versions used in this session will appear here</div>
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: COLORS.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>This Session</div>
                    {promptVersions.map((pv, i) => (
                      <div key={i} style={{ padding: "10px 12px", border: `1px solid ${COLORS.border}`, borderRadius: 8, background: COLORS.surface }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}><Tag color="purple" size="xs">{pv.agent}</Tag></div>
                        <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: COLORS.text, fontWeight: 600 }}>{pv.version}</div>
                        <div style={{ fontSize: 11, color: COLORS.textFaint, marginTop: 3 }}>{pv.source || "Loaded from local prompts/"}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=DM+Mono:wght@400;500;600&display=swap');
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: ${COLORS.borderStrong}; border-radius: 2px; }
        @keyframes bounce { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-3px); } }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
