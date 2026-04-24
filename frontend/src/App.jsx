import { useEffect, useMemo, useState } from "react";

import { getChat, postChat, streamChat } from "./api";


function getOrCreateSessionId() {
  const existing = localStorage.getItem("session_id");
  if (existing) return existing;
  const created = crypto.randomUUID();
  localStorage.setItem("session_id", created);
  return created;
}


export default function App() {
  const sessionId = useMemo(() => getOrCreateSessionId(), []);

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [useStreaming, setUseStreaming] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadHistory() {
      try {
        const data = await getChat(sessionId);
        setMessages(data.messages || []);
      } catch {
        setError("Could not load chat history.");
      }
    }

    loadHistory();
  }, [sessionId]);

  async function handleSubmit(event) {
    event.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;

    setError("");
    setInput("");
    setIsLoading(true);

    if (useStreaming) {
      setMessages((prev) => [
        ...prev,
        { role: "user", content: trimmed },
        { role: "assistant", content: "" },
      ]);

      try {
        await streamChat(sessionId, trimmed, (streamEvent) => {
          if (streamEvent.type === "delta") {
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
          }
        });
      } catch (streamError) {
        setError(streamError.message || "Streaming failed.");
      } finally {
        setIsLoading(false);
      }
      return;
    }

    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);

    try {
      const data = await postChat(sessionId, trimmed);
      setMessages(data.messages || []);
    } catch (chatError) {
      setError(chatError.message || "Request failed.");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="container">
      <h1>AI Chat</h1>
      <p className="session">Session: {sessionId}</p>

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
        <label className="streaming-toggle">
          <input
            type="checkbox"
            checked={useStreaming}
            onChange={(event) => setUseStreaming(event.target.checked)}
            disabled={isLoading}
          />
          Streaming
        </label>

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

