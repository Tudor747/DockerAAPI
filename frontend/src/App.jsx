import { useCallback, useEffect, useMemo, useState } from "react";

import { getChat, streamChat } from "./api";


const BROWSER_SESSION_STORAGE_KEY = "browser_session_id";
const CURRENT_CHAT_STORAGE_KEY = "current_chat_id";
const LEGACY_CHAT_STORAGE_KEY = "chat_session_id";
const LEGACY_SESSION_STORAGE_KEY = "session_id";


function createSessionId() {
  if (crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}


function getOrCreateStoredId(storageKey) {
  const existing = localStorage.getItem(storageKey);
  if (existing) return existing;

  const created = createSessionId();
  localStorage.setItem(storageKey, created);
  return created;
}


function getOrCreateChatId() {
  const existing = localStorage.getItem(CURRENT_CHAT_STORAGE_KEY);
  if (existing) return existing;

  const legacyChat = localStorage.getItem(LEGACY_CHAT_STORAGE_KEY);
  if (legacyChat) {
    localStorage.setItem(CURRENT_CHAT_STORAGE_KEY, legacyChat);
    return legacyChat;
  }

  const legacy = localStorage.getItem(LEGACY_SESSION_STORAGE_KEY);
  if (legacy) {
    localStorage.setItem(CURRENT_CHAT_STORAGE_KEY, legacy);
    return legacy;
  }

  const created = createSessionId();
  localStorage.setItem(CURRENT_CHAT_STORAGE_KEY, created);
  return created;
}


export default function App() {
  const browserSessionId = useMemo(
    () => getOrCreateStoredId(BROWSER_SESSION_STORAGE_KEY),
    [],
  );
  const [sessionId, setSessionId] = useState(() => getOrCreateChatId());

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  const loadHistory = useCallback(async () => {
    try {
      const data = await getChat(sessionId);
      setMessages(data.messages || []);
    } catch {
      setError("Could not load chat history.");
    }
  }, [sessionId]);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  function handleNewChat() {
    const nextSessionId = createSessionId();
    localStorage.setItem(CURRENT_CHAT_STORAGE_KEY, nextSessionId);
    setSessionId(nextSessionId);
    setMessages([]);
    setInput("");
    setError("");
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;

    setError("");
    setInput("");
    setIsLoading(true);

    setMessages((prev) => [
      ...prev,
      { role: "user", content: trimmed },
      { role: "assistant", content: "" },
    ]);

    try {
      await streamChat(sessionId, browserSessionId, trimmed, (streamEvent) => {
        if (streamEvent.type !== "delta") return;

        setMessages((prev) => {
          const next = [...prev];
          const lastIndex = next.length - 1;
          if (lastIndex >= 0 && next[lastIndex].role === "assistant") {
            next[lastIndex] = {
              ...next[lastIndex],
              content: next[lastIndex].content + streamEvent.content,
            };
          }
          return next;
        });
      });

      await loadHistory();
    } catch (streamError) {
      setError(streamError.message || "Streaming failed.");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="container">
      <header className="header">
        <div>
          <h1>AI Chat</h1>
          <p className="session">Chat: {sessionId}</p>
        </div>
        <button type="button" className="secondary-button" onClick={handleNewChat}>
          New chat
        </button>
      </header>

      <section className="messages">
        {messages.length === 0 && <p className="empty">No messages yet.</p>}
        {messages.map((message, index) => (
          <article key={`${message.role}-${index}`} className={`message ${message.role}`}>
            <span className="role">{message.role}</span>
            <p>{message.content}</p>
          </article>
        ))}
      </section>

      {error && <p className="error">{error}</p>}

      <form onSubmit={handleSubmit} className="composer">
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Type your message..."
          rows={3}
          disabled={isLoading}
        />

        <button type="submit" disabled={isLoading || !input.trim()}>
          {isLoading ? "Sending..." : "Send"}
        </button>
      </form>
    </main>
  );
}
