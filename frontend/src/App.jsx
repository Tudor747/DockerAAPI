import { useCallback, useEffect, useMemo, useState } from "react";

import { deleteChat, getChat, listChats, streamChat } from "./api";


const BROWSER_SESSION_STORAGE_KEY = "browser_session_id";
const CURRENT_CHAT_STORAGE_KEY = "current_chat_id";
const CHAT_LIST_STORAGE_KEY = "chat_sessions";
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

function getStoredChats(currentSessionId) {
  try {
    const parsed = JSON.parse(localStorage.getItem(CHAT_LIST_STORAGE_KEY) || "[]");
    if (Array.isArray(parsed)) {
      const chats = parsed.filter((chat) => chat && typeof chat.session_id === "string");
      if (chats.some((chat) => chat.session_id === currentSessionId)) {
        return chats;
      }
      return [
        { session_id: currentSessionId, title: `Chat ${currentSessionId.slice(0, 8)}`, message_count: 0 },
        ...chats,
      ];
    }
  } catch {
    // Fall back to the current chat when old localStorage data is malformed.
  }

  return [{ session_id: currentSessionId, title: `Chat ${currentSessionId.slice(0, 8)}`, message_count: 0 }];
}


function saveStoredChats(chats) {
  localStorage.setItem(CHAT_LIST_STORAGE_KEY, JSON.stringify(chats));
}


function chatTitleFromMessages(messages, sessionId) {
  const firstUserMessage = messages.find((message) => message.role === "user" && message.content.trim());
  if (!firstUserMessage) return `Chat ${sessionId.slice(0, 8)}`;

  const title = firstUserMessage.content.trim().replace(/\s+/g, " ");
  return title.length > 42 ? `${title.slice(0, 42)}...` : title;
}


function mergeChats(...chatGroups) {
  const merged = new Map();
  for (const chats of chatGroups) {
    for (const chat of chats) {
      merged.set(chat.session_id, { ...merged.get(chat.session_id), ...chat });
    }
  }
  return Array.from(merged.values());
}


export default function App() {
  const browserSessionId = useMemo(
    () => getOrCreateStoredId(BROWSER_SESSION_STORAGE_KEY),
    [],
  );
  const [sessionId, setSessionId] = useState(() => getOrCreateChatId());
  const [chats, setChats] = useState(() => getStoredChats(getOrCreateChatId()));

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  const loadHistory = useCallback(async () => {
    try {
      const data = await getChat(sessionId);
      const nextMessages = data.messages || [];
      setMessages(nextMessages);
      setChats((prev) => {
        const next = mergeChats(
          prev,
          [
            {
              session_id: sessionId,
              title: chatTitleFromMessages(nextMessages, sessionId),
              message_count: nextMessages.length,
            },
          ],
        );
        saveStoredChats(next);
        return next;
      });
    } catch {
      setError("Could not load chat history.");
    }
  }, [sessionId]);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    async function loadChats() {
      try {
        const data = await listChats(browserSessionId);
        setChats((prev) => {
          const next = mergeChats(prev, data.sessions || []);
          saveStoredChats(next);
          return next;
        });
      } catch {
        setChats((prev) => prev);
      }
    }

    loadChats();
  }, [browserSessionId]);

  function activateChat(nextSessionId) {
    if (nextSessionId === sessionId || isLoading) return;
    localStorage.setItem(CURRENT_CHAT_STORAGE_KEY, nextSessionId);
    setSessionId(nextSessionId);
    setInput("");
    setError("");
  }

  function handleNewChat() {
    const nextSessionId = createSessionId();
    const nextChat = {
      session_id: nextSessionId,
      title: `Chat ${nextSessionId.slice(0, 8)}`,
      message_count: 0,
    };
    localStorage.setItem(CURRENT_CHAT_STORAGE_KEY, nextSessionId);
    setSessionId(nextSessionId);
    setChats((prev) => {
      const next = mergeChats([nextChat], prev);
      saveStoredChats(next);
      return next;
    });
    setMessages([]);
    setInput("");
    setError("");
  }

  async function handleDeleteChat(chatSessionId) {
    if (isLoading) return;

    try {
      await deleteChat(chatSessionId);
    } catch (deleteError) {
      setError(deleteError.message || "Could not delete conversation.");
      return;
    }

    setChats((prev) => {
      const next = prev.filter((chat) => chat.session_id !== chatSessionId);
      saveStoredChats(next);

      if (chatSessionId === sessionId) {
        const nextActiveChat = next[0];
        if (nextActiveChat) {
          localStorage.setItem(CURRENT_CHAT_STORAGE_KEY, nextActiveChat.session_id);
          setSessionId(nextActiveChat.session_id);
        } else {
          const created = createSessionId();
          localStorage.setItem(CURRENT_CHAT_STORAGE_KEY, created);
          setSessionId(created);
          setMessages([]);
        }
      }

      return next;
    });
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

  function handleComposerKeyDown(event) {
    if (event.key !== "Enter" || event.shiftKey) return;

    event.preventDefault();
    event.currentTarget.form.requestSubmit();
  }

  return (
    <main className="app-shell">
      <aside className="sidebar" aria-label="Conversations">
        <div className="sidebar-header">
          <h2>Conversations</h2>
          <button type="button" className="icon-button" onClick={handleNewChat} title="New chat">
            +
          </button>
        </div>

        <nav className="chat-list">
          {chats.length === 0 && <p className="empty">No conversations yet.</p>}
          {chats.map((chat) => (
            <div
              key={chat.session_id}
              className={`chat-list-item ${chat.session_id === sessionId ? "active" : ""}`}
            >
              <button
                type="button"
                className="chat-select"
                onClick={() => activateChat(chat.session_id)}
                disabled={isLoading && chat.session_id !== sessionId}
                title={chat.title}
              >
                <span>{chat.title}</span>
                <small>{chat.message_count || 0} messages</small>
              </button>
              <button
                type="button"
                className="delete-button"
                onClick={() => handleDeleteChat(chat.session_id)}
                disabled={isLoading}
                title="Delete conversation"
              >
                x
              </button>
            </div>
          ))}
        </nav>
      </aside>

      <section className="chat-panel">
        <header className="header">
          <div>
            <h1>AI Chat</h1>
            <p className="session">Chat: {sessionId}</p>
          </div>
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
            onKeyDown={handleComposerKeyDown}
            placeholder="Type your message..."
            rows={3}
            disabled={isLoading}
          />

          <button type="submit" disabled={isLoading || !input.trim()}>
            {isLoading ? "Sending..." : "Send"}
          </button>
        </form>
      </section>
    </main>
  );
}
