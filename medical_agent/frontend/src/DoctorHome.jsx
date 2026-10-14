import { useEffect, useState } from "react";
import { api } from "./api.js";

export default function DoctorHome() {
  const [status, setStatus] = useState("open");
  const [cases, setCases] = useState([]);
  const [selected, setSelected] = useState(null);

  const load = () => api("GET", `/doctor/cases?status=${status}`).then(setCases);
  useEffect(() => {
    load();
    const t = setInterval(load, 15000); // new escalations show up without a reload
    return () => clearInterval(t);
  }, [status]);

  return (
    <div className="doctor">
      <aside className="card queue">
        <div className="tabs">
          {["open", "plan_given", "closed", "all"].map((s) => (
            <button key={s} className={s === status ? "tab on" : "tab"} onClick={() => setStatus(s)}>
              {s.replace("_", " ")}
            </button>
          ))}
        </div>
        {cases.length === 0 && <p className="muted small">No cases here.</p>}
        {cases.map((c) => (
          <button key={c.id} className={"case-row" + (selected === c.id ? " on" : "")} onClick={() => setSelected(c.id)}>
            <span className={`badge ${c.urgency}`}>{c.urgency}</span>
            <strong>{c.patient}</strong>
            <span className="small muted">{c.reason}</span>
            <span className="small muted">{new Date(c.created_at).toLocaleString()}</span>
          </button>
        ))}
      </aside>
      <section className="detail">
        {selected ? (
          <CaseDetail
            id={selected}
            onChanged={() => {
              load();
            }}
          />
        ) : (
          <p className="muted center">Select a case from the queue.</p>
        )}
      </section>
    </div>
  );
}

function CaseDetail({ id, onChanged }) {
  const [c, setC] = useState(null);
  const reload = () => api("GET", `/doctor/cases/${id}`).then(setC);
  useEffect(() => {
    setC(null);
    reload();
  }, [id]);
  if (!c) return <p className="muted">Loading…</p>;

  const ctx = c.patient_context;
  const p = ctx.patient;
  return (
    <>
      <div className="card">
        <div className="row-between">
          <h2>{c.patient}</h2>
          <span className={`badge ${c.urgency}`}>{c.urgency}</span>
        </div>
        <div className="small muted">
          {p.age} y · {p.sex} · {p.height_cm ?? "?"} cm · {p.weight_kg ?? "?"} kg
          {p.bmi && ` · BMI ${p.bmi}`} · {p.experience} · status: {c.status.replace("_", " ")}
        </div>
        <div className="small">Conditions: {ctx.conditions.map((x) => x.name).join(", ") || "none"}</div>
        <h3>Why it was escalated</h3>
        <p>{c.reason}</p>
        <h3>Assistant's summary</h3>
        <p className="pre">{c.summary}</p>
      </div>
      <div className="card">
        <h3>Progress</h3>
        <ProgressTable progress={ctx.progress} />
        {ctx.memory.length > 0 && (
          <>
            <h3>Facts from earlier chats</h3>
            {ctx.memory.map((n, i) => (
              <div key={i} className="small">
                • {n}
              </div>
            ))}
          </>
        )}
      </div>
      <div className="card">
        <h3>Conversation</h3>
        <div className="transcript">
          {c.transcript.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              <div className="small muted">
                {m.role}
                {m.decision && ` · ${m.decision}`} · {new Date(m.created_at).toLocaleString()}
              </div>
              <div className="content">{m.content}</div>
            </div>
          ))}
        </div>
      </div>
      {c.plans.map((pl) => (
        <div key={pl.id} className="card">
          <h3>Plan given by Dr. {pl.doctor}</h3>
          <p className="pre">{pl.instructions}</p>
          {pl.exercises.map((e, i) => (
            <div key={i} className="small">
              • {e.name}: {e.sets} × {e.amount} {e.unit} {e.notes && `(${e.notes})`}
            </div>
          ))}
        </div>
      ))}
      {c.status !== "closed" && (
        <PlanForm
          caseId={c.id}
          approved={ctx.approved_exercises}
          onDone={() => {
            reload();
            onChanged();
          }}
        />
      )}
    </>
  );
}

function ProgressTable({ progress }) {
  const rows = [
    ["Active days", progress.last_week.active_days, progress.this_week.active_days],
    ["Average pain", progress.last_week.pain_avg ?? "–", progress.this_week.pain_avg ?? "–"],
    ["Highest pain", progress.last_week.pain_max ?? "–", progress.this_week.pain_max ?? "–"],
  ];
  return (
    <>
      <table>
        <thead>
          <tr>
            <th />
            <th>Last week</th>
            <th>This week</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, a, b]) => (
            <tr key={label}>
              <td>{label}</td>
              <td>{a}</td>
              <td>{b}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {progress.signals.map((s) => (
        <div key={s.code} className={`small ${s.escalate ? "error" : "muted"}`}>
          {s.text}
        </div>
      ))}
    </>
  );
}

function PlanForm({ caseId, approved, onDone }) {
  const [all, setAll] = useState([]);
  const [instructions, setInstructions] = useState("");
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");
  useEffect(() => {
    api("GET", "/exercises").then(setAll);
  }, []);
  const safe = new Set(approved.map((e) => e.activity_type));

  const update = (i, k, v) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));

  async function submit(e) {
    e.preventDefault();
    setError("");
    try {
      await api("POST", `/doctor/cases/${caseId}/plan`, {
        instructions,
        exercises: rows.map((r) => ({ ...r, sets: Number(r.sets), amount: Number(r.amount) })),
      });
      setInstructions("");
      setRows([]);
      onDone();
    } catch (err) {
      setError(err.message);
    }
  }

  async function close() {
    await api("POST", `/doctor/cases/${caseId}/close`);
    onDone();
  }

  return (
    <form className="card" onSubmit={submit}>
      <h3>Give a plan</h3>
      <textarea
        rows={4}
        value={instructions}
        onChange={(e) => setInstructions(e.target.value)}
        placeholder="Advice and instructions for the patient"
        required
      />
      {rows.map((r, i) => (
        <div key={i} className="row plan-row">
          <select value={r.activity_type} onChange={(e) => update(i, "activity_type", e.target.value)} required>
            <option value="">Exercise…</option>
            {all.map((x) => (
              <option key={x.activity_type} value={x.activity_type}>
                {x.name} ({x.unit}){safe.has(x.activity_type) ? "" : " – not in safety grid"}
              </option>
            ))}
          </select>
          <input type="number" min="1" value={r.sets} onChange={(e) => update(i, "sets", e.target.value)} title="Sets" />
          <input
            type="number"
            min="0.1"
            step="any"
            value={r.amount}
            onChange={(e) => update(i, "amount", e.target.value)}
            placeholder="Amount"
            required
          />
          <input value={r.notes} onChange={(e) => update(i, "notes", e.target.value)} placeholder="Notes" />
          <button type="button" className="link" onClick={() => setRows(rows.filter((_, j) => j !== i))}>
            Remove
          </button>
        </div>
      ))}
      <button
        type="button"
        className="link"
        onClick={() => setRows([...rows, { activity_type: "", sets: 1, amount: "", notes: "" }])}
      >
        + Add exercise
      </button>
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button className="primary">Send plan to patient</button>
        <button type="button" className="link" onClick={close}>
          Close case without a plan
        </button>
      </div>
    </form>
  );
}
