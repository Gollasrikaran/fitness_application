import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";

const PENDING_TEXT = {
  starter: "Your first exercise plan is being prepared. A doctor on our team checks every plan before you start, so please wait for it.",
  easier: "The easier plan you asked for is with your doctor. Until it's approved, keep to your current plan or rest if something hurts.",
  update: "Your plan is being updated for your health conditions. A doctor will review it before it changes.",
};

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
  const { progress, conditions, doctor_plan, pending_plan, open_case, memory } = context;
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
      {pending_plan && (
        <div className="card notice routine">
          <strong>Waiting for your doctor</strong>
          <div className="small">{PENDING_TEXT[pending_plan.kind]}</div>
          <div className="small muted">Requested {pending_plan.requested_on}</div>
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
          {!pending_plan && doctor_plan.exercises.length > 0 && <TooHard plan={doctor_plan} onDone={onLogged} />}
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
      <LogForm exercises={doctor_plan?.exercises || []} onLogged={onLogged} />
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
  // The doctor's plan first; anything else is still loggable.
  const inPlan = new Set(exercises.map((e) => e.activity_type));
  const options = [...all].sort((a, b) => inPlan.has(b.activity_type) - inPlan.has(a.activity_type));
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
            {inPlan.has(e.activity_type) ? "" : " (not in your plan)"}
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

function TooHard({ plan, onDone }) {
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState([]);
  const [pain, setPain] = useState("");
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState("");

  const toggle = (a) => setPicked(picked.includes(a) ? picked.filter((x) => x !== a) : [...picked, a]);

  async function submit(e) {
    e.preventDefault();
    setMsg("");
    try {
      const out = await api("POST", "/plans/too-hard", {
        activity_types: picked,
        pain_level: pain === "" ? null : Number(pain),
        note: note.trim() || null,
      });
      setOpen(false);
      setPicked([]);
      setPain("");
      setNote("");
      setMsg(
        out.status === "doctor_case"
          ? "Because of the pain, a doctor will look at this. Please rest and avoid movements that hurt."
          : "Thanks. Your doctor will review an easier plan for you."
      );
      onDone();
    } catch (err) {
      setMsg(err.message);
    }
  }

  if (!open)
    return (
      <>
        <button className="link" onClick={() => setOpen(true)}>
          Is this plan too hard?
        </button>
        {msg && <div className="small muted">{msg}</div>}
      </>
    );
  return (
    <form className="too-hard" onSubmit={submit}>
      <div className="small muted">Which exercises are too hard? Leave all unticked if it's all of them.</div>
      {plan.exercises.map((e) => (
        <label key={e.activity_type} className="check">
          <input type="checkbox" checked={picked.includes(e.activity_type)} onChange={() => toggle(e.activity_type)} />
          {e.name}
        </label>
      ))}
      <label>
        Pain while doing them (0–10, optional)
        <input type="number" min="0" max="10" value={pain} onChange={(e) => setPain(e.target.value)} />
      </label>
      <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Anything else? (optional)" maxLength={1000} />
      {msg && <div className="small error">{msg}</div>}
      <div className="actions">
        <button className="primary">Ask for an easier plan</button>
        <button type="button" className="link" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}
