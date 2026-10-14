import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";

const DECISION_LABEL = {
  self_care: "Self-care advice",
  clarify: "Needs a bit more info",
  doctor: "Sent to a doctor",
  emergency: "Urgent: seek care now",
};

export default function PatientHome() {
  const [messages, setMessages] = useState([]);
  const [context, setContext] = useState(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef(null);

  const refresh = () =>
    Promise.all([api("GET", "/chat").then(setMessages), api("GET", "/agent/context").then(setContext)]).catch(
      (err) => setError(`Couldn't load your data: ${err.message}`)
    );

  useEffect(() => {
    refresh();
  }, []);
  useEffect(() => {
    // Braces matter: newer browsers return a Promise from scrollIntoView, and an
    // effect must return nothing or a cleanup function, or React crashes.
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send(e) {
    e.preventDefault();
    const message = text.trim();
    if (!message) return;
    setText("");
    setError("");
    setBusy(true);
    setMessages((m) => [...m, { id: "pending", role: "user", content: message }]);
    try {
      await api("POST", "/chat", { message });
    } catch (err) {
      setError(err.message);
      setText(message);
    } finally {
      await refresh();
      setBusy(false);
    }
  }

  return (
    <div className="patient">
      <section className="chat card">
        <div className="messages">
          {messages.length === 0 && (
            <p className="muted">
              Tell me how you're feeling, ask about your exercises, or describe any pain. I can see your profile and
              this week's progress. If something needs a doctor, I'll pass it on.
            </p>
          )}
          {messages.map((m) => (
            <Message key={m.id} m={m} />
          ))}
          {busy && <div className="msg assistant muted">Thinking…</div>}
          <div ref={endRef} />
        </div>
        {error && <p className="error">{error}</p>}
        <form className="composer" onSubmit={send}>
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="e.g. my lower back feels stiff after yesterday's walk"
            maxLength={2000}
          />
          <button className="primary" disabled={busy || !text.trim()}>
            Send
          </button>
        </form>
      </section>
      <aside className="side">
        {context && <Sidebar context={context} onLogged={refresh} />}
      </aside>
    </div>
  );
}

function Message({ m }) {
  return (
    <div className={`msg ${m.role}`}>
      {m.role === "doctor" && <div className="badge doctor">Doctor's plan</div>}
      {m.decision && <div className={`badge ${m.decision}`}>{DECISION_LABEL[m.decision]}</div>}
      <div className="content">{m.content}</div>
      {m.exercises?.length > 0 && (
        <div className="exercises">
          {m.exercises.map((e) => (
            <div key={e.activity_type} className="exercise">
              <strong>{e.display_name}</strong> · {e.default_sets} × {e.default_amount} {e.unit}
              {e.notes?.map((n, i) => (
                <div key={i} className="small muted">
                  {n}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Sidebar({ context, onLogged }) {
  const { progress, conditions, doctor_plan, open_case, memory } = context;
  const tw = progress.this_week;
  const lw = progress.last_week;
  return (
    <>
      {open_case && (
        <div className={`card notice ${open_case.urgency}`}>
          <strong>A doctor is reviewing your case</strong>
          <div className="small">
            Opened {open_case.opened_on} · {open_case.urgency}
          </div>
        </div>
      )}
      {doctor_plan && (
        <div className="card">
          <h3>Your doctor's plan</h3>
          <div className="small muted">
            Dr. {doctor_plan.doctor} · {doctor_plan.given_on}
          </div>
          <p className="pre">{doctor_plan.instructions}</p>
          {doctor_plan.exercises.map((e, i) => (
            <div key={i} className="small">
              • {e.name}: {e.sets} × {e.amount} {e.unit} {e.notes && `(${e.notes})`}
            </div>
          ))}
        </div>
      )}
      <div className="card">
        <h3>This week</h3>
        <div className="stats">
          <Stat label="Active days" now={tw.active_days} before={lw.active_days} />
          <Stat label="Avg pain" now={tw.pain_avg} before={lw.pain_avg} lowerIsBetter />
        </div>
        {Object.entries(tw.exercises).map(([name, e]) => (
          <div key={name} className="small">
            {name}: {e.total} {e.unit} in {e.sessions} session{e.sessions > 1 ? "s" : ""}
          </div>
        ))}
        {progress.signals.map((s) => (
          <div key={s.code} className={`small ${s.escalate ? "error" : "muted"}`}>
            {s.text}
          </div>
        ))}
      </div>
      <LogForm exercises={context.approved_exercises} onLogged={onLogged} />
      <div className="card">
        <h3>Your conditions</h3>
        <div className="small">
          {conditions.map((c) => c.name).join(", ") || "None listed"}
        </div>
        {memory.length > 0 && (
          <>
            <h3>What I remember</h3>
            {memory.map((n, i) => (
              <div key={i} className="small muted">
                • {n}
              </div>
            ))}
          </>
        )}
      </div>
    </>
  );
}

function Stat({ label, now, before, lowerIsBetter }) {
  const diff = now != null && before != null ? Math.round((now - before) * 10) / 10 : null;
  const good = diff != null && (lowerIsBetter ? diff < 0 : diff > 0);
  return (
    <div className="stat">
      <div className="value">{now ?? "–"}</div>
      <div className="small muted">{label}</div>
      {diff != null && diff !== 0 && (
        <div className={`small ${good ? "good" : "error"}`}>
          {diff > 0 ? "+" : ""}
          {diff} vs last week
        </div>
      )}
    </div>
  );
}

function LogForm({ exercises, onLogged }) {
  const [all, setAll] = useState([]);
  const [form, setForm] = useState({ activity_type: "", sets: 1, amount: "", pain_level: "" });
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api("GET", "/exercises").then(setAll);
  }, []);
  // Approved exercises first; the rest are still loggable (e.g. from a doctor's plan).
  const approved = new Set(exercises.map((e) => e.activity_type));
  const options = [...all].sort((a, b) => approved.has(b.activity_type) - approved.has(a.activity_type));
  const current = all.find((e) => e.activity_type === form.activity_type);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setMsg("");
    try {
      await api("POST", "/progress", {
        activity_type: form.activity_type,
        sets: Number(form.sets),
        amount: Number(form.amount),
        pain_level: form.pain_level === "" ? null : Number(form.pain_level),
      });
      setForm({ ...form, amount: "", pain_level: "" });
      setMsg("Logged");
      onLogged();
    } catch (err) {
      setMsg(err.message);
    }
  }

  return (
    <form className="card log" onSubmit={submit}>
      <h3>Log today's exercise</h3>
      <select value={form.activity_type} onChange={set("activity_type")} required>
        <option value="">Choose exercise…</option>
        {options.map((e) => (
          <option key={e.activity_type} value={e.activity_type}>
            {e.name}
            {approved.has(e.activity_type) ? "" : " (not in your safe list)"}
          </option>
        ))}
      </select>
      <div className="row">
        <label>
          Sets
          <input type="number" min="1" max="20" value={form.sets} onChange={set("sets")} required />
        </label>
        <label>
          {current ? `Amount (${current.unit})` : "Amount"}
          <input type="number" min="0.1" step="any" value={form.amount} onChange={set("amount")} required />
        </label>
        <label>
          Pain after (0–10)
          <input type="number" min="0" max="10" value={form.pain_level} onChange={set("pain_level")} />
        </label>
      </div>
      <button className="primary">Log</button>
      {msg && <span className="small muted"> {msg}</span>}
    </form>
  );
}
