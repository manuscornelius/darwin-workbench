const COUNCIL_URL = "http://127.0.0.1:8001";

export async function listSessions() {
  const response = await fetch(`${COUNCIL_URL}/sessions?user_id=manus&limit=50`);
  if (!response.ok) throw new Error("Failed to load sessions");
  return response.json();
}

export async function getSession(sessionId) {
  const response = await fetch(`${COUNCIL_URL}/sessions/${sessionId}`);
  if (!response.ok) throw new Error("Failed to load session");
  return response.json();
}
