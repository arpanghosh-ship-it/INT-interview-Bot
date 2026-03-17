import { useState, useEffect } from "react";

type AppState = "form" | "launching" | "active" | "exiting" | "exited";

const API = "/api";
const MAX_WORDS = 1000;

// Count words in a string
const countWords = (text: string): number => {
  return text.trim() === "" ? 0 : text.trim().split(/\s+/).length;
};

const Index = () => {
  const [state, setState] = useState<AppState>("form");
  const [meetLink, setMeetLink] = useState("");
  const [persona, setPersona] = useState("");
  const [error, setError] = useState("");

  const wordCount = countWords(persona);
  const isOverLimit = wordCount > MAX_WORDS;

  // Poll /status every 5s while active — detect if bot crashes on its own
  useEffect(() => {
    if (state !== "active") return;
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API}/status`);
        const data = await res.json();
        if (data.status === "idle") setState("exited");
      } catch {}
    }, 5000);
    return () => clearInterval(interval);
  }, [state]);

  const handleLaunch = async () => {
    if (!meetLink.trim()) {
      setError("Please enter a Google Meet link.");
      return;
    }
    if (!persona.trim()) {
      setError("Please describe the bot persona.");
      return;
    }
    if (isOverLimit) {
      setError(`Persona is too long. Please keep it under ${MAX_WORDS} words.`);
      return;
    }
    setError("");
    setState("launching");

    try {
      const res = await fetch(`${API}/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ meetLink: meetLink.trim(), persona: persona.trim() }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `Server error ${res.status}` }));
        throw new Error(err.detail || `Server error ${res.status}`);
      }
      setState("active");
    } catch (err: any) {
      setError(`Failed to launch bot: ${err.message}`);
      setState("form");
    }
  };

  const handleExit = async () => {
    setState("exiting");
    try {
      await fetch(`${API}/stop`, { method: "POST" });
    } catch (err) {
      console.error("Stop request failed:", err);
    }
    setState("exited");
  };

  const handleReset = () => {
    setMeetLink("");
    setPersona("");
    setError("");
    setState("form");
  };

  return (
    <div className="bot-page">
      <div className="bot-card">
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.25rem" }}>
          <span style={{ fontSize: "2rem" }}>🤖</span>
          <h1>Interview Bot</h1>
        </div>
        <p className="subtitle">Launch an AI-powered bot into your Google Meet interview.</p>

        {/* Form State */}
        {state === "form" && (
          <div style={{ animation: "fadeIn 0.4s ease-out" }}>
            <div className="bot-field-group">
              <label className="bot-label">📎 Google Meet Link</label>
              <input
                className="bot-input"
                type="url"
                placeholder="https://meet.google.com/abc-defg-hij"
                value={meetLink}
                onChange={(e) => setMeetLink(e.target.value)}
              />
            </div>

            <div className="bot-field-group">
              <label className="bot-label">🎭 Bot Persona</label>
              <textarea
                className="bot-textarea"
                placeholder="Describe how the bot should behave during the interview. E.g., 'Act as a senior React developer interviewer. Ask technical questions about hooks, state management, and performance optimization. Be friendly but thorough.'"
                value={persona}
                onChange={(e) => setPersona(e.target.value)}
                // ── REMOVED maxLength={1000} — was limiting characters, not words ──
              />
              {/* ── Word counter (replaces old character counter) ── */}
              <div
                className="bot-char-count"
                style={{
                  color: isOverLimit
                    ? "hsl(var(--destructive))"
                    : wordCount > MAX_WORDS * 0.9
                    ? "hsl(var(--warning, 38 92% 50%))"
                    : undefined,
                  fontWeight: isOverLimit ? 600 : undefined,
                }}
              >
                {wordCount} / {MAX_WORDS} words
                {isOverLimit && " — too long, please shorten"}
              </div>
            </div>

            {error && (
              <p style={{
                color: "hsl(var(--destructive))",
                fontSize: "0.85rem",
                marginBottom: "1rem",
                animation: "fadeIn 0.2s ease-out"
              }}>
                ⚠️ {error}
              </p>
            )}

            <button
              className="bot-btn bot-btn-primary"
              onClick={handleLaunch}
              disabled={isOverLimit}
              style={{ opacity: isOverLimit ? 0.5 : 1, cursor: isOverLimit ? "not-allowed" : "pointer" }}
            >
              🚀 Launch Bot
            </button>
          </div>
        )}

        {/* Launching State */}
        {state === "launching" && (
          <div className="bot-loading">
            <div className="spinner spinner-dark" style={{ width: 40, height: 40, borderWidth: 4 }} />
            <p>Launching bot into your meeting...</p>
            <p style={{ fontSize: "0.8rem", opacity: 0.6 }}>This may take a moment</p>
          </div>
        )}

        {/* Active State */}
        {state === "active" && (
          <div className="bot-status">
            <div className="bot-status-icon success">✅</div>
            <h2>Bot is in your meeting!</h2>
            <p>The interview bot has joined and is ready to go.</p>

            <div style={{
              background: "hsl(var(--muted))",
              borderRadius: "calc(var(--radius) - 2px)",
              padding: "1rem",
              marginBottom: "1.5rem",
              textAlign: "left",
              fontSize: "0.85rem"
            }}>
              <div style={{ color: "hsl(var(--muted-foreground))", marginBottom: "0.25rem" }}>
                <strong>Meeting:</strong> {meetLink}
              </div>
              <div style={{ color: "hsl(var(--muted-foreground))" }}>
                <strong>Persona:</strong> {persona.length > 80 ? persona.slice(0, 80) + "…" : persona}
              </div>
            </div>

            <button className="bot-btn bot-btn-exit" onClick={handleExit}>
              ⏻ Exit Bot
            </button>
          </div>
        )}

        {/* Exiting State */}
        {state === "exiting" && (
          <div className="bot-loading">
            <div className="spinner" style={{ width: 40, height: 40, borderWidth: 4, borderColor: "hsl(var(--destructive) / 0.3)", borderTopColor: "hsl(var(--destructive))" }} />
            <p>Removing bot from the meeting...</p>
          </div>
        )}

        {/* Exited State */}
        {state === "exited" && (
          <div className="bot-status">
            <div className="bot-status-icon exited">👋</div>
            <h2>Bot has exited the meeting</h2>
            <p>The interview bot has left your Google Meet session.</p>
            <button className="bot-btn bot-btn-outline" onClick={handleReset}>
              🔄 Start New Session
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default Index;