const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

export async function getChat(sessionId) {
  const response = await fetch(`${API_BASE}/chat/${sessionId}`);
  if (!response.ok) {
    throw new Error("Failed to fetch chat history.");
  }
  return response.json();
}

export async function postChat(sessionId, message) {
  const response = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });

  if (!response.ok) {
    throw new Error("Failed to send message.");
  }
  return response.json();
}

export async function streamChat(sessionId, message, onEvent) {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });

  if (!response.ok || !response.body) {
    throw new Error("Failed to start streaming response.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      onEvent(event);
      if (event.type === "error") {
        throw new Error(event.message || "Streaming failed.");
      }
    }
  }

  if (buffer.trim()) {
    const event = JSON.parse(buffer);
    onEvent(event);
    if (event.type === "error") {
      throw new Error(event.message || "Streaming failed.");
    }
  }
}

