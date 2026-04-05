import { useState } from "react";

const API = "/api";

type State = "form" | "launching" | "active" | "exiting" | "exited";

const Index = () => {
  const [state, setState] = useState<State>("form");
  const [error, setError] = useState("");
  const [launchStatus, setLaunchStatus] = useState("");
  const [meetLink, setMeetLink] = useState("");
  const [sessionId, setSessionId] = useState("");

  // Form fields
  const [interviewerName, setInterviewerName] = useState("Alex");
  const [interviewType, setInterviewType] = useState("Technical");
  const [targetRole, setTargetRole] = useState("");
  const [experienceLevel, setExperienceLevel] = useState("1-3 years");
  const [keyTopics, setKeyTopics] = useState("");
  const [tone, setTone] = useState("Professional");
  const [duration, setDuration] = useState("30");
  const [candidateEmail, setCandidateEmail] = useState("");

  // ── Launch: generate prompt + create meeting + start bot ──────────────────
  const handleLaunchBot = async () => {
    if (!targetRole.trim()) {
      setError("Please enter the Target Role before launching.");
      return;
    }

    setState("launching");
    setError("");

    try {
      // Step 1: Build the interview prompt (instant — pure template, no GPT call)
      setLaunchStatus("Building interview plan...");
      const promptRes = await fetch(`${API}/generate-prompt`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          interviewer_name: interviewerName || "Alex",
          interview_type: interviewType,
          target_role: targetRole,
          experience_level: experienceLevel,
          key_topics: keyTopics,
          tone,
          duration_minutes: parseInt(duration),
        }),
      });
      if (!promptRes.ok) {
        const e = await promptRes.json().catch(() => ({}));
        throw new Error(e.detail || `Prompt generation failed (${promptRes.status})`);
      }
      const { persona } = await promptRes.json();

      // Step 2: Create Google Meet (bot = host)
      setLaunchStatus("Creating Google Meet...");
      const meetRes = await fetch(`${API}/create-meeting`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: `INT Interview — ${targetRole} (${interviewType})`,
          duration_minutes: parseInt(duration) + 15,
          candidate_email: candidateEmail.trim() || null,
        }),
      });
      if (!meetRes.ok) {
        const e = await meetRes.json().catch(() => ({}));
        throw new Error(e.detail || `Failed to create meeting (${meetRes.status})`);
      }
      const { meet_link } = await meetRes.json();
      setMeetLink(meet_link);

      // Step 3: Launch the bot
      setLaunchStatus("Launching bot into meeting...");
      const startRes = await fetch(`${API}/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          meetLink: meet_link,
          persona,
          duration_minutes: parseInt(duration),
          interviewer_name: interviewerName || "Alex",
          target_role: targetRole,
          interview_type: interviewType,
          tone,
        }),
      });
      if (!startRes.ok) {
        const e = await startRes.json().catch(() => ({}));
        throw new Error(e.detail || `Server error ${startRes.status}`);
      }
      const { session_id } = await startRes.json();
      setSessionId(session_id);
      setState("active");

    } catch (err: any) {
      setError(`Launch failed: ${err.message}`);
      setState("form");
    }
  };

  const handleExit = async () => {
    setState("exiting");
    try {
      await fetch(`${API}/stop/${sessionId}`, { method: "POST" });
    } catch {}
    setState("exited");
  };

  const handleReset = () => {
    setMeetLink(""); setError(""); setLaunchStatus(""); setSessionId("");
    setState("form");
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text).catch(() => {});
  };

  // ── Styles ────────────────────────────────────────────────────────────────
  const s: Record<string, React.CSSProperties> = {
    page: {
      minHeight: "100vh",
      background: "linear-gradient(135deg, #0a0a0f 0%, #12122a 50%, #0a0a0f 100%)",
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: "2rem 1rem",
      fontFamily: "'DM Sans', 'Segoe UI', sans-serif",
    },
    card: {
      width: "100%", maxWidth: "560px",
      background: "rgba(255,255,255,0.035)",
      border: "1px solid rgba(255,255,255,0.09)",
      borderRadius: "22px", padding: "2.25rem 2.5rem",
      backdropFilter: "blur(24px)",
      boxShadow: "0 30px 80px rgba(0,0,0,0.6), 0 0 0 1px rgba(99,102,241,0.08)",
    },
    header: { display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.3rem" },
    title: { fontSize: "1.65rem", fontWeight: 700, color: "#fff", margin: 0, letterSpacing: "-0.5px" },
    subtitle: { color: "rgba(255,255,255,0.4)", fontSize: "0.88rem", marginBottom: "1.75rem", marginTop: "0.2rem" },
    divider: { height: "1px", background: "rgba(255,255,255,0.07)", margin: "1.25rem 0" },
    sectionLabel: {
      color: "rgba(99,102,241,0.7)", fontSize: "0.68rem", fontWeight: 700,
      letterSpacing: "1.8px", textTransform: "uppercase" as const,
      marginBottom: "0.85rem", marginTop: "1.5rem",
    },
    row: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.7rem", marginBottom: "0.7rem" },
    field: { marginBottom: "0.7rem" },
    label: { display: "block", color: "rgba(255,255,255,0.55)", fontSize: "0.75rem", fontWeight: 500, marginBottom: "0.35rem" },
    input: {
      width: "100%", background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)",
      borderRadius: "10px", padding: "0.6rem 0.85rem", color: "#fff", fontSize: "0.88rem",
      outline: "none", boxSizing: "border-box" as const, transition: "border-color 0.15s",
    },
    select: {
      width: "100%", background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)",
      borderRadius: "10px", padding: "0.6rem 0.85rem", color: "#fff", fontSize: "0.88rem",
      outline: "none", cursor: "pointer", boxSizing: "border-box" as const,
      appearance: "none" as const,
      backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='rgba(255,255,255,0.4)' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E")`,
      backgroundRepeat: "no-repeat",
      backgroundPosition: "right 0.85rem center",
    },
    error: {
      color: "#ff6b6b", fontSize: "0.82rem",
      background: "rgba(255,107,107,0.08)", border: "1px solid rgba(255,107,107,0.2)",
      borderRadius: "9px", padding: "0.6rem 0.9rem", marginBottom: "0.75rem",
    },
    btnLaunch: {
      width: "100%",
      background: "linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)",
      color: "#fff", border: "none", borderRadius: "12px", padding: "0.9rem",
      fontSize: "0.95rem", fontWeight: 700, cursor: "pointer", marginTop: "1.5rem",
      letterSpacing: "0.3px",
      boxShadow: "0 4px 20px rgba(99,102,241,0.3)",
    },
    btnExit: {
      width: "100%", background: "rgba(239,68,68,0.12)", color: "#ef4444",
      border: "1px solid rgba(239,68,68,0.25)", borderRadius: "12px", padding: "0.9rem",
      fontSize: "0.93rem", fontWeight: 600, cursor: "pointer", marginTop: "1rem",
    },
    btnOutline: {
      width: "100%", background: "rgba(255,255,255,0.04)", color: "rgba(255,255,255,0.55)",
      border: "1px solid rgba(255,255,255,0.1)", borderRadius: "12px", padding: "0.75rem",
      fontSize: "0.87rem", fontWeight: 500, cursor: "pointer", marginTop: "0.5rem",
    },
    btnCopy: {
      background: "rgba(99,102,241,0.12)", color: "rgba(99,102,241,0.85)",
      border: "1px solid rgba(99,102,241,0.25)", borderRadius: "8px",
      padding: "0.3rem 0.7rem", fontSize: "0.74rem", fontWeight: 600, cursor: "pointer",
      marginLeft: "0.5rem", flexShrink: 0,
    },
    spinnerWrap: { textAlign: "center" as const, padding: "2.5rem 0" },
    spinner: {
      width: 44, height: 44, border: "3px solid rgba(99,102,241,0.2)",
      borderTop: "3px solid #6366f1", borderRadius: "50%",
      animation: "spin 0.8s linear infinite", margin: "0 auto 1.25rem",
    },
    statusCenter: { textAlign: "center" as const, padding: "0.5rem 0" },
    statusIcon: { fontSize: "2.8rem", marginBottom: "0.85rem", display: "block" },
    statusTitle: { fontSize: "1.25rem", fontWeight: 700, color: "#fff", marginBottom: "0.4rem" },
    statusSub: { color: "rgba(255,255,255,0.45)", fontSize: "0.88rem", marginBottom: "1.25rem" },
    meetLinkBox: {
      display: "flex", alignItems: "center",
      background: "rgba(16,185,129,0.07)", border: "1px solid rgba(16,185,129,0.2)",
      borderRadius: "10px", padding: "0.7rem 0.9rem", marginBottom: "0.9rem", gap: "0.5rem",
    },
    meetLinkText: { color: "#10b981", fontSize: "0.83rem", fontWeight: 600, wordBreak: "break-all" as const, flex: 1 },
    sessionBadge: {
      display: "inline-block", background: "rgba(99,102,241,0.08)",
      border: "1px solid rgba(99,102,241,0.18)", borderRadius: "6px",
      padding: "0.18rem 0.55rem", fontSize: "0.68rem", color: "rgba(99,102,241,0.65)",
      fontFamily: "monospace", marginBottom: "0.9rem",
    },
    infoBox: {
      background: "rgba(255,255,255,0.04)", borderRadius: "10px",
      padding: "0.9rem 1rem", marginBottom: "1.25rem", fontSize: "0.8rem",
    },
    infoRow: { color: "rgba(255,255,255,0.5)", marginBottom: "0.35rem", lineHeight: 1.5 },
    badge: {
      display: "inline-flex", alignItems: "center", gap: "0.4rem",
      background: "rgba(99,102,241,0.1)", border: "1px solid rgba(99,102,241,0.18)",
      borderRadius: "8px", padding: "0.3rem 0.7rem", fontSize: "0.75rem",
      color: "rgba(99,102,241,0.8)", marginBottom: "1.25rem",
    },
  };

  return (
    <div style={s.page}>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fadeIn { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:translateY(0); } }
        input::placeholder { color:rgba(255,255,255,0.22); }
        select option { background:#12122a; color:#fff; }
        input:focus, select:focus { border-color:rgba(99,102,241,0.5) !important; }
      `}</style>

      <div style={s.card}>

        {/* ── HEADER ──────────────────────────────────────────────────────── */}
        <div style={s.header}>
          <span style={{ fontSize: "1.75rem" }}>🤖</span>
          <h1 style={s.title}>Interview Bot</h1>
        </div>
        <p style={s.subtitle}>Configure and launch your AI interviewer.</p>

        {/* ── FORM ────────────────────────────────────────────────────────── */}
        {state === "form" && (
          <div style={{ animation: "fadeIn 0.3s ease-out" }}>
            <div style={s.badge}>
              🔗 Google Meet link is created automatically — bot is the host
            </div>

            {/* Interviewer setup */}
            <div style={s.sectionLabel}>Interviewer</div>
            <div style={s.row}>
              <div>
                <label style={s.label}>Name</label>
                <input style={s.input} type="text" placeholder="Alex"
                  value={interviewerName} onChange={e => setInterviewerName(e.target.value)} />
              </div>
              <div>
                <label style={s.label}>Type</label>
                <select style={s.select} value={interviewType} onChange={e => setInterviewType(e.target.value)}>
                  <option>Technical</option>
                  <option>HR</option>
                  <option>Behavioral</option>
                  <option>Mock Interview</option>
                  <option>Case Study</option>
                  <option>System Design</option>
                </select>
              </div>
            </div>

            {/* Candidate setup */}
            <div style={s.sectionLabel}>Candidate</div>
            <div style={s.field}>
              <label style={s.label}>Target Role *</label>
              <input style={s.input} type="text" placeholder="e.g. AI Engineer, Backend Developer, HR Manager"
                value={targetRole} onChange={e => setTargetRole(e.target.value)} />
            </div>

            <div style={s.row}>
              <div>
                <label style={s.label}>Experience Level</label>
                <select style={s.select} value={experienceLevel} onChange={e => setExperienceLevel(e.target.value)}>
                  <option>Fresher</option>
                  <option>1-3 years</option>
                  <option>3-5 years</option>
                  <option>Senior (5+ years)</option>
                </select>
              </div>
              <div>
                <label style={s.label}>Tone</label>
                <select style={s.select} value={tone} onChange={e => setTone(e.target.value)}>
                  <option>Professional</option>
                  <option>Friendly</option>
                  <option>Strict</option>
                  <option>Casual</option>
                </select>
              </div>
            </div>

            {/* Session setup */}
            <div style={s.sectionLabel}>Session</div>
            <div style={s.field}>
              <label style={s.label}>Key Topics to Cover (optional)</label>
              <input style={s.input} type="text" placeholder="e.g. Python, Machine Learning, System Design, LLMs"
                value={keyTopics} onChange={e => setKeyTopics(e.target.value)} />
            </div>

            <div style={s.row}>
              <div>
                <label style={s.label}>Duration</label>
                <select style={s.select} value={duration} onChange={e => setDuration(e.target.value)}>
                  <option value="15">15 minutes</option>
                  <option value="30">30 minutes</option>
                  <option value="45">45 minutes</option>
                  <option value="60">60 minutes</option>
                </select>
              </div>
              <div>
                <label style={s.label}>Candidate Email (optional)</label>
                <input style={s.input} type="email" placeholder="candidate@example.com"
                  value={candidateEmail} onChange={e => setCandidateEmail(e.target.value)} />
              </div>
            </div>

            {error && <div style={s.error}>⚠️ {error}</div>}

            <button style={s.btnLaunch} onClick={handleLaunchBot}>
              🚀 Launch Interview Bot
            </button>
          </div>
        )}

        {/* ── LAUNCHING ───────────────────────────────────────────────────── */}
        {state === "launching" && (
          <div style={s.spinnerWrap}>
            <div style={s.spinner} />
            <p style={{ color: "#fff", fontWeight: 600, margin: "0 0 0.4rem" }}>
              {launchStatus || "Preparing..."}
            </p>
            <p style={{ color: "rgba(255,255,255,0.35)", fontSize: "0.82rem", margin: 0 }}>
              Bot will join as host — no admission required
            </p>
          </div>
        )}

        {/* ── ACTIVE ──────────────────────────────────────────────────────── */}
        {state === "active" && (
          <div style={{ animation: "fadeIn 0.3s ease-out" }}>
            <div style={s.statusCenter}>
              <span style={s.statusIcon}>✅</span>
              <div style={s.statusTitle}>Bot is live as host</div>
              <div style={s.statusSub}>Share the meeting link with your candidate.</div>
            </div>

            {sessionId && (
              <div style={s.sessionBadge}>Session: {sessionId.slice(0, 8)}</div>
            )}

            <div style={s.meetLinkBox}>
              <span style={s.meetLinkText}>{meetLink}</span>
              <button style={s.btnCopy} onClick={() => copyToClipboard(meetLink)}>
                📋 Copy
              </button>
            </div>

            <div style={s.infoBox}>
              <div style={s.infoRow}>
                <strong style={{ color: "rgba(255,255,255,0.75)" }}>Role:</strong>{" "}
                {targetRole} ({experienceLevel})
              </div>
              <div style={s.infoRow}>
                <strong style={{ color: "rgba(255,255,255,0.75)" }}>Type:</strong>{" "}
                {interviewType} · {tone} · {duration} min
              </div>
              <div style={s.infoRow}>
                <strong style={{ color: "rgba(255,255,255,0.75)" }}>Interviewer:</strong>{" "}
                {interviewerName}
              </div>
              {keyTopics && (
                <div style={s.infoRow}>
                  <strong style={{ color: "rgba(255,255,255,0.75)" }}>Topics:</strong>{" "}
                  {keyTopics}
                </div>
              )}
              {candidateEmail && (
                <div style={s.infoRow}>
                  <strong style={{ color: "rgba(255,255,255,0.75)" }}>Invite sent to:</strong>{" "}
                  {candidateEmail}
                </div>
              )}
            </div>

            <button style={s.btnExit} onClick={handleExit}>⏻ Exit Bot</button>
          </div>
        )}

        {/* ── EXITING ─────────────────────────────────────────────────────── */}
        {state === "exiting" && (
          <div style={s.spinnerWrap}>
            <div style={{ ...s.spinner, borderTopColor: "#ef4444" }} />
            <p style={{ color: "#fff", fontWeight: 600, margin: 0 }}>
              Removing bot from meeting...
            </p>
          </div>
        )}

        {/* ── EXITED ──────────────────────────────────────────────────────── */}
        {state === "exited" && (
          <div style={{ ...s.statusCenter, animation: "fadeIn 0.3s ease-out" }}>
            <span style={s.statusIcon}>👋</span>
            <div style={s.statusTitle}>Bot has left the meeting</div>
            <div style={s.statusSub}>The session has ended.</div>
            <button style={s.btnOutline} onClick={handleReset}>🔄 Start New Session</button>
          </div>
        )}

      </div>
    </div>
  );
};

export default Index;