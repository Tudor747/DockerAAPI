const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

async function getErrorMessage(response, fallbackMessage) {
  try {
    const payload = await response.json();
    if (typeof payload?.detail === "string" && payload.detail.trim()) {
      return payload.detail;
    }
    if (typeof payload?.message === "string" && payload.message.trim()) {
      return payload.message;
    }
  } catch {
    // Ignore JSON parsing failures and use fallback message.
  }
  return fallbackMessage;
}

export async function getChat(sessionId) {
  const response = await fetch(`${API_BASE}/chat/${sessionId}`);
  if (!response.ok) {
    throw new Error(await getErrorMessage(response, "Failed to fetch chat history."));
  }
  return response.json();
}

export async function listChats(browserSessionId) {
  const params = new URLSearchParams({ browser_session_id: browserSessionId });
  const response = await fetch(`${API_BASE}/chat?${params.toString()}`);
  if (!response.ok) {
    throw new Error(await getErrorMessage(response, "Failed to fetch conversations."));
  }
  return response.json();
}

export async function deleteChat(sessionId) {
  const response = await fetch(`${API_BASE}/chat/${sessionId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(await getErrorMessage(response, "Failed to delete conversation."));
  }
}

export async function streamChat(sessionId, browserSessionId, message, onEvent) {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      browser_session_id: browserSessionId,
      message,
    }),
  });

  if (!response.ok || !response.body) {
    throw new Error(await getErrorMessage(response, "Failed to start streaming response."));
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
