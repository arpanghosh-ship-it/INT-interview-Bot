import { useState, useEffect } from "react";

type AppState = "form" | "generating" | "preview" | "launching" | "active" | "exiting" | "exited";

const API = "/api";

const Index = () => {
  const [state, setState] = useState<AppState>("form");
  const [meetLink, setMeetLink] = useState("");
  const [error, setError] = useState("");
  const [generatedPersona, setGeneratedPersona] = useState("");

  // Interview detail fields
  const [interviewerName, setInterviewerName] = useState("Alex");
  const [interviewType, setInterviewType] = useState("Technical");
  const [targetRole, setTargetRole] = useState("");
  const [experienceLevel, setExperienceLevel] = useState("1-3 years");
  const [keyTopics, setKeyTopics] = useState("");
  const [tone, setTone] = useState("Professional");
  const [duration, setDuration] = useState("30");

  // Poll /status every 5s while active
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

  // ── Step 1: Generate persona only ────────────────────────────────────────
  const handleGeneratePersona = async () => {
    if (!meetLink.trim()) { setError("Please enter a Google Meet link."); return; }
    if (!targetRole.trim()) { setError("Please enter the target role."); return; }
    setError("");
    setState("generating");

    try {
      const promptRes = await fetch(`${API}/generate-prompt`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          interviewer_name: interviewerName.trim(),
          interview_type: interviewType,
          target_role: targetRole.trim(),
          experience_level: experienceLevel,
          key_topics: keyTopics.trim(),
          tone: tone,
          duration_minutes: parseInt(duration),
        }),
      });
      if (!promptRes.ok) throw new Error(`Prompt generation failed: ${promptRes.status}`);
      const { persona } = await promptRes.json();
      setGeneratedPersona(persona);
      setState("preview");
    } catch (err: any) {
      setError(`Failed: ${err.message}`);
      setState("form");
    }
  };

  // ── Step 2: Launch bot with (possibly edited) persona ─────────────────────
  const handleLaunchBot = async () => {
    setState("launching");
    try {
      const startRes = await fetch(`${API}/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ meetLink: meetLink.trim(), persona: generatedPersona }),
      });
      if (!startRes.ok) {
        const err = await startRes.json().catch(() => ({ detail: `Server error ${startRes.status}` }));
        throw new Error(err.detail || `Server error ${startRes.status}`);
      }
      setState("active");
    } catch (err: any) {
      setError(`Failed to launch: ${err.message}`);
      setState("preview");
    }
  };

  const handleExit = async () => {
    setState("exiting");
    try { await fetch(`${API}/stop`, { method: "POST" }); } catch {}
    setState("exited");
  };

  const handleReset = () => {
    setMeetLink(""); setError(""); setTargetRole("");
    setKeyTopics(""); setGeneratedPersona("");
    setState("form");
  };

  // ── Styles ────────────────────────────────────────────────────────────────
  const styles: Record<string, React.CSSProperties> = {
    page: {
      minHeight: "100vh",
      background: "linear-gradient(135deg, #0f0f0f 0%, #1a1a2e 50%, #0f0f0f 100%)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "2rem 1rem",
      fontFamily: "'DM Sans', 'Segoe UI', sans-serif",
    },
    card: {
      width: "100%",
      maxWidth: "580px",
      background: "rgba(255,255,255,0.04)",
      border: "1px solid rgba(255,255,255,0.1)",
      borderRadius: "20px",
      padding: "2.5rem",
      backdropFilter: "blur(20px)",
      boxShadow: "0 25px 60px rgba(0,0,0,0.5)",
    },
    header: {
      display: "flex",
      alignItems: "center",
      gap: "0.75rem",
      marginBottom: "0.5rem",
    },
    title: {
      fontSize: "1.7rem",
      fontWeight: 700,
      color: "#fff",
      margin: 0,
      letterSpacing: "-0.5px",
    },
    subtitle: {
      color: "rgba(255,255,255,0.45)",
      fontSize: "0.9rem",
      marginBottom: "2rem",
      marginTop: "0.25rem",
    },
    sectionTitle: {
      color: "rgba(255,255,255,0.5)",
      fontSize: "0.7rem",
      fontWeight: 600,
      letterSpacing: "1.5px",
      textTransform: "uppercase" as const,
      marginBottom: "1rem",
      marginTop: "1.75rem",
    },
    row: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "0.75rem",
      marginBottom: "0.75rem",
    },
    fieldGroup: { marginBottom: "0.75rem" },
    label: {
      display: "block",
      color: "rgba(255,255,255,0.6)",
      fontSize: "0.78rem",
      fontWeight: 500,
      marginBottom: "0.4rem",
    },
    input: {
      width: "100%",
      background: "rgba(255,255,255,0.06)",
      border: "1px solid rgba(255,255,255,0.12)",
      borderRadius: "10px",
      padding: "0.65rem 0.9rem",
      color: "#fff",
      fontSize: "0.9rem",
      outline: "none",
      boxSizing: "border-box" as const,
    },
    select: {
      width: "100%",
      background: "rgba(255,255,255,0.06)",
      border: "1px solid rgba(255,255,255,0.12)",
      borderRadius: "10px",
      padding: "0.65rem 0.9rem",
      color: "#fff",
      fontSize: "0.9rem",
      outline: "none",
      cursor: "pointer",
      boxSizing: "border-box" as const,
    },
    textarea: {
      width: "100%",
      background: "rgba(255,255,255,0.06)",
      border: "1px solid rgba(255,255,255,0.12)",
      borderRadius: "10px",
      padding: "0.75rem 0.9rem",
      color: "#fff",
      fontSize: "0.82rem",
      fontFamily: "monospace",
      outline: "none",
      resize: "vertical" as const,
      minHeight: "320px",
      boxSizing: "border-box" as const,
      lineHeight: 1.6,
    },
    divider: {
      height: "1px",
      background: "rgba(255,255,255,0.08)",
      margin: "1.5rem 0",
    },
    error: {
      color: "#ff6b6b",
      fontSize: "0.83rem",
      marginBottom: "1rem",
      background: "rgba(255,107,107,0.1)",
      border: "1px solid rgba(255,107,107,0.2)",
      borderRadius: "8px",
      padding: "0.6rem 0.9rem",
    },
    btnPrimary: {
      width: "100%",
      background: "linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)",
      color: "#fff",
      border: "none",
      borderRadius: "12px",
      padding: "0.9rem",
      fontSize: "0.95rem",
      fontWeight: 600,
      cursor: "pointer",
      marginTop: "1.25rem",
      letterSpacing: "0.2px",
    },
    btnExit: {
      width: "100%",
      background: "rgba(239,68,68,0.15)",
      color: "#ef4444",
      border: "1px solid rgba(239,68,68,0.3)",
      borderRadius: "12px",
      padding: "0.9rem",
      fontSize: "0.95rem",
      fontWeight: 600,
      cursor: "pointer",
      marginTop: "1rem",
    },
    btnOutline: {
      width: "100%",
      background: "rgba(255,255,255,0.04)",
      color: "rgba(255,255,255,0.6)",
      border: "1px solid rgba(255,255,255,0.12)",
      borderRadius: "12px",
      padding: "0.75rem",
      fontSize: "0.88rem",
      fontWeight: 500,
      cursor: "pointer",
      marginTop: "0.5rem",
    },
    statusCenter: { textAlign: "center" as const, padding: "1rem 0" },
    statusIcon: { fontSize: "3rem", marginBottom: "1rem", display: "block" },
    statusTitle: { fontSize: "1.3rem", fontWeight: 700, color: "#fff", marginBottom: "0.5rem" },
    statusSub: { color: "rgba(255,255,255,0.5)", fontSize: "0.9rem", marginBottom: "1.5rem" },
    infoBox: {
      background: "rgba(255,255,255,0.05)",
      borderRadius: "10px",
      padding: "1rem",
      marginBottom: "1.5rem",
      textAlign: "left" as const,
      fontSize: "0.83rem",
    },
    infoRow: { color: "rgba(255,255,255,0.55)", marginBottom: "0.4rem", lineHeight: 1.5 },
    spinnerWrap: { textAlign: "center" as const, padding: "2.5rem 0" },
    spinner: {
      width: 44,
      height: 44,
      border: "3px solid rgba(99,102,241,0.2)",
      borderTop: "3px solid #6366f1",
      borderRadius: "50%",
      animation: "spin 0.8s linear infinite",
      margin: "0 auto 1.25rem",
    },
    previewHint: {
      fontSize: "0.78rem",
      color: "rgba(255,255,255,0.35)",
      marginTop: "0.5rem",
      textAlign: "center" as const,
    },
  };

  return (
    <div style={styles.page}>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        input::placeholder, textarea::placeholder { color: rgba(255,255,255,0.25); }
        select option { background: #1a1a2e; color: #fff; }
        input:focus, textarea:focus, select:focus { border-color: rgba(99,102,241,0.6) !important; }
      `}</style>

      <div style={styles.card}>
        <div style={styles.header}>
          <span style={{ fontSize: "1.8rem" }}>🤖</span>
          <h1 style={styles.title}>Interview Bot</h1>
        </div>
        <p style={styles.subtitle}>Configure your AI interviewer and launch into Google Meet.</p>

        {/* ── FORM ──────────────────────────────────────────────────────────── */}
        {state === "form" && (
          <div style={{ animation: "fadeIn 0.3s ease-out" }}>
            <div style={styles.fieldGroup}>
              <label style={styles.label}>📎 Google Meet Link</label>
              <input
                style={styles.input}
                type="url"
                placeholder="https://meet.google.com/abc-defg-hij"
                value={meetLink}
                onChange={(e) => setMeetLink(e.target.value)}
              />
            </div>

            <div style={styles.divider} />
            <div style={styles.sectionTitle}>Interviewer Setup</div>

            <div style={styles.row}>
              <div>
                <label style={styles.label}>Interviewer Name</label>
                <input style={styles.input} type="text" placeholder="Alex"
                  value={interviewerName} onChange={(e) => setInterviewerName(e.target.value)} />
              </div>
              <div>
                <label style={styles.label}>Interview Type</label>
                <select style={styles.select} value={interviewType} onChange={(e) => setInterviewType(e.target.value)}>
                  <option>Technical</option>
                  <option>HR</option>
                  <option>Mock Interview</option>
                  <option>Behavioral</option>
                  <option>Case Study</option>
                  <option>System Design</option>
                </select>
              </div>
            </div>

            <div style={styles.row}>
              <div>
                <label style={styles.label}>Target Role *</label>
                <input style={styles.input} type="text" placeholder="AI Engineer"
                  value={targetRole} onChange={(e) => setTargetRole(e.target.value)} />
              </div>
              <div>
                <label style={styles.label}>Experience Level</label>
                <select style={styles.select} value={experienceLevel} onChange={(e) => setExperienceLevel(e.target.value)}>
                  <option>Fresher</option>
                  <option>1-3 years</option>
                  <option>3-5 years</option>
                  <option>Senior (5+ years)</option>
                </select>
              </div>
            </div>

            <div style={styles.sectionTitle}>Optional Settings</div>

            <div style={styles.fieldGroup}>
              <label style={styles.label}>Key Topics to Cover</label>
              <input style={styles.input} type="text"
                placeholder="Machine Learning, Python, LLMs, System Design"
                value={keyTopics} onChange={(e) => setKeyTopics(e.target.value)} />
            </div>

            <div style={styles.row}>
              <div>
                <label style={styles.label}>Interview Tone</label>
                <select style={styles.select} value={tone} onChange={(e) => setTone(e.target.value)}>
                  <option>Professional</option>
                  <option>Friendly</option>
                  <option>Strict</option>
                  <option>Casual</option>
                </select>
              </div>
              <div>
                <label style={styles.label}>Duration (minutes)</label>
                <select style={styles.select} value={duration} onChange={(e) => setDuration(e.target.value)}>
                  <option value="15">15 min</option>
                  <option value="30">30 min</option>
                  <option value="45">45 min</option>
                  <option value="60">60 min</option>
                </select>
              </div>
            </div>

            {error && <div style={styles.error}>⚠️ {error}</div>}

            <button style={styles.btnPrimary} onClick={handleGeneratePersona}>
              🎯 Generate Persona
            </button>
          </div>
        )}

        {/* ── GENERATING ────────────────────────────────────────────────────── */}
        {state === "generating" && (
          <div style={styles.spinnerWrap}>
            <div style={styles.spinner} />
            <p style={{ color: "#fff", fontWeight: 600, margin: "0 0 0.4rem" }}>
              Generating interview persona...
            </p>
            <p style={{ color: "rgba(255,255,255,0.4)", fontSize: "0.83rem", margin: 0 }}>
              AI is crafting a structured interview plan
            </p>
          </div>
        )}

        {/* ── PREVIEW (editable persona) ────────────────────────────────────── */}
        {state === "preview" && (
          <div style={{ animation: "fadeIn 0.35s ease-out" }}>
            <div style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: "0.6rem",
              marginTop: "0.25rem",
            }}>
              <div style={{
                fontSize: "0.78rem",
                fontWeight: 600,
                letterSpacing: "1.2px",
                textTransform: "uppercase" as const,
                color: "rgba(255,255,255,0.5)",
              }}>
                ✨ Generated Persona
              </div>
              <div style={{
                fontSize: "0.72rem",
                color: "rgba(99,102,241,0.8)",
                background: "rgba(99,102,241,0.1)",
                border: "1px solid rgba(99,102,241,0.2)",
                borderRadius: "6px",
                padding: "0.2rem 0.5rem",
              }}>
                Editable
              </div>
            </div>

            <textarea
              style={styles.textarea}
              value={generatedPersona}
              onChange={(e) => setGeneratedPersona(e.target.value)}
              spellCheck={false}
            />

            <p style={styles.previewHint}>
              Review and edit the persona above, then launch the bot.
            </p>

            {error && <div style={{ ...styles.error, marginTop: "0.75rem" }}>⚠️ {error}</div>}

            <button style={styles.btnPrimary} onClick={handleLaunchBot}>
              🚀 Launch Bot
            </button>

            <button style={styles.btnOutline} onClick={() => setState("form")}>
              ← Edit Details
            </button>
          </div>
        )}

        {/* ── LAUNCHING ─────────────────────────────────────────────────────── */}
        {state === "launching" && (
          <div style={styles.spinnerWrap}>
            <div style={styles.spinner} />
            <p style={{ color: "#fff", fontWeight: 600, margin: "0 0 0.4rem" }}>
              Launching bot into your meeting...
            </p>
            <p style={{ color: "rgba(255,255,255,0.4)", fontSize: "0.83rem", margin: 0 }}>
              Joining Google Meet — this may take a moment
            </p>
          </div>
        )}

        {/* ── ACTIVE ────────────────────────────────────────────────────────── */}
        {state === "active" && (
          <div style={styles.statusCenter}>
            <span style={styles.statusIcon}>✅</span>
            <div style={styles.statusTitle}>Bot is live in your meeting!</div>
            <div style={styles.statusSub}>The AI interviewer has joined and is ready.</div>
            <div style={styles.infoBox}>
              <div style={styles.infoRow}><strong style={{ color: "rgba(255,255,255,0.8)" }}>Role:</strong> {targetRole} ({experienceLevel})</div>
              <div style={styles.infoRow}><strong style={{ color: "rgba(255,255,255,0.8)" }}>Type:</strong> {interviewType} · {tone} · {duration} min</div>
              <div style={styles.infoRow}><strong style={{ color: "rgba(255,255,255,0.8)" }}>Interviewer:</strong> {interviewerName}</div>
              {keyTopics && <div style={styles.infoRow}><strong style={{ color: "rgba(255,255,255,0.8)" }}>Topics:</strong> {keyTopics}</div>}
              <div style={{ ...styles.infoRow, marginTop: "0.5rem", wordBreak: "break-all" as const }}>
                <strong style={{ color: "rgba(255,255,255,0.8)" }}>Meet:</strong> {meetLink}
              </div>
            </div>
            <button style={styles.btnExit} onClick={handleExit}>⏻ Exit Bot</button>
          </div>
        )}

        {/* ── EXITING ───────────────────────────────────────────────────────── */}
        {state === "exiting" && (
          <div style={styles.spinnerWrap}>
            <div style={{ ...styles.spinner, borderTopColor: "#ef4444" }} />
            <p style={{ color: "#fff", fontWeight: 600, margin: 0 }}>
              Removing bot from meeting...
            </p>
          </div>
        )}

        {/* ── EXITED ────────────────────────────────────────────────────────── */}
        {state === "exited" && (
          <div style={styles.statusCenter}>
            <span style={styles.statusIcon}>👋</span>
            <div style={styles.statusTitle}>Bot has left the meeting</div>
            <div style={styles.statusSub}>The interview session has ended.</div>
            <button style={styles.btnOutline} onClick={handleReset}>🔄 Start New Session</button>
          </div>
        )}
      </div>
    </div>
  );
};

export default Index;