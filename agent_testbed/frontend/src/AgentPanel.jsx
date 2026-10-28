import { useEffect, useState } from "react";
import { api } from "./api.js";

// Doctor tab: the agent's own data for one patient (temporary database).
// "Generate plan" assesses the patient and drafts a plan; the draft is
// reviewed here. The doctor has the final say: exercises and doses can be
// changed freely, and the safety grid only shows a small warning.

const KIND = { starter: "First plan", update: "Update to current plan" };
const SOURCE = { ai: "AI draft", rules: "Rules draft", doctor: "Doctor must write" };
const dose = (d) => (d ? `${d.sets} × ${d.amount}` : "—");

export default function AgentPanel({ patientId, doctor, doctors, version, onChanged }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setError("");
    api("GET", `/patients/${patientId}/agent`)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [patientId, version]);

  async function generate() {
    if (data?.pending && !window.confirm("A draft is already waiting. Replace it with a new one?")) return;
    setBusy(true);
    setError("");
    try {
      await api("POST", `/patients/${patientId}/assess`, { doctor_id: doctor.id });
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (!data) return error ? <p className="error">{error}</p> : null;
  const doctorName = (id) => doctors.find((d) => d.id === id)?.name || "a doctor";
  const { plan, pending, assessment, open_case } = data;

  return (
    <>
      <div className="card row-between">
        <span className="small muted">{busy ? "Assessing the record and drafting… (about 20 s)" : "Exercise plan"}</span>
        <button className="primary" onClick={generate} disabled={busy}>
          {busy ? "Working…" : pending ? "Generate again" : "Generate plan"}
        </button>
      </div>
      {error && <p className="error small pad">{error}</p>}
      {open_case && <CaseCard c={open_case} doctor={doctor} onChanged={onChanged} />}
      {pending && (
        <ReviewCard key={pending.id} p={pending} patientId={patientId} assessment={assessment} doctor={doctor} onChanged={onChanged} />
      )}
      <div className="card">
        <h3>Current plan</h3>
        {plan ? (
          <>
            <div className="small muted">
              Approved by Dr. {doctorName(plan.doctor_id)} · {plan.given_on}
            </div>
            <p className="small pre">{plan.instructions}</p>
            {plan.exercises.map((e, i) => (
              <div key={i} className="small row-item">
                • {e.name}: {e.sets} × {e.amount} {e.unit} {e.notes && <span className="muted">({e.notes})</span>}
              </div>
            ))}
          </>
        ) : (
          <div className="small muted">No approved plan yet.</div>
        )}
      </div>
    </>
  );
}

// The latest readings the reading rules tested (last 90 days), e.g.
// "BP 150/95 (2026-10-20) · Sugar 260 mg/dL (2026-10-20) · no Hb, SpO2, pulse".
const READING = {
  bp: ["BP", (r) => `${r.sys}/${r.dia}`],
  sugar: ["Sugar", (r) => `${r.low === r.high ? r.high : `${r.low}–${r.high}`} mg/dL`],
  hb: ["Hb", (r) => `${r.value} g/dL`],
  spo2: ["SpO2", (r) => `${r.value}%`],
  pulse: ["Pulse", (r) => `${r.value}/min`],
};
function readingsText(readings) {
  const known = Object.keys(READING).filter((k) => k in readings);
  const seen = known.filter((k) => readings[k]).map((k) => `${READING[k][0]} ${READING[k][1](readings[k])} (${readings[k].date})`);
  const none = known.filter((k) => !readings[k]).map((k) => READING[k][0]);
  return [...seen, none.length && `none in the last 90 days for ${none.join(", ")}`].filter(Boolean).join(" · ");
}

function AssessmentView({ a }) {
  return (
    <div className="assessment">
      <div className="row-between">
        <strong className="small">Assessment</strong>
        <span className={`badge sev-${a.severity}`}>{a.severity}</span>
      </div>
      {a.problem && <p className="small">{a.problem}{a.body_area && <span className="muted"> · {a.body_area}</span>}</p>}
      {a.readings && Object.keys(a.readings).length > 0 && (
        <p className="small muted">Readings used for the plan: {readingsText(a.readings)}</p>
      )}
      {a.severe_reasons.length > 0 && (
        <ul className="small reasons">
          {a.severe_reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
      <details className="small">
        <summary>
          Conditions ({a.conditions.length}){a.concerns.length > 0 && ` · concerns (${a.concerns.length})`}
        </summary>
        {a.conditions.map((c) => (
          <div key={c.code} className="row-item">
            <strong>{c.name}</strong> <span className="muted">· {c.found_by}{c.complaint_only && " · from a complaint only"}</span>
            {c.evidence.map((e, i) => (
              <div key={i} className="muted evidence">{e}</div>
            ))}
          </div>
        ))}
        {a.concerns.map((c, i) => (
          <div key={i} className="row-item">⚠ {c}</div>
        ))}
        {a.missing.length > 0 && <div className="row-item muted">Missing: {a.missing.join("; ")}</div>}
      </details>
    </div>
  );
}

function ReviewCard({ p, patientId, assessment, doctor, onChanged }) {
  const [exercises, setExercises] = useState(p.exercises);
  const [instructions, setInstructions] = useState(p.instructions);
  const [catalog, setCatalog] = useState([]);
  const [warnings, setWarnings] = useState({});
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const params = new URLSearchParams({ conditions: p.conditions.join(","), patient_id: patientId });
    api("GET", `/exercises?${params}`)
      .then(setCatalog)
      .catch((e) => setError(e.message));
  }, [p.conditions, patientId]);

  // Small warnings from the safety grid and the patient's BP reading, refreshed as the doctor edits. They never block.
  useEffect(() => {
    const valid = exercises.filter((e) => e.sets >= 1 && e.amount > 0);
    const t = setTimeout(() => {
      api("POST", "/plans/check", { conditions: p.conditions, exercises: valid.map(payload), patient_id: patientId })
        .then((out) => setWarnings(out.warnings))
        .catch(() => {});
    }, 300);
    return () => clearTimeout(t);
  }, [exercises, p.conditions, patientId]);

  const update = (i, field, value) => setExercises((xs) => xs.map((x, j) => (j === i ? { ...x, [field]: value } : x)));
  const remove = (i) => setExercises((xs) => xs.filter((_, j) => j !== i));
  function add(kind) {
    const e = catalog.find((c) => c.activity_type === kind);
    if (!e) return;
    const notes = e.verdict === "modify" ? e.notes : "";
    setExercises((xs) => [...xs, { activity_type: kind, name: e.name, unit: e.unit, sets: e.default_sets,
                                   amount: e.default_amount, notes }]);
  }

  async function act(path, body) {
    setError("");
    try {
      await api("POST", `/proposals/${p.id}/${path}`, { doctor_id: doctor.id, ...body });
      onChanged();
    } catch (e) {
      setError(e.message);
    }
  }

  const unused = catalog.filter((c) => !exercises.some((e) => e.activity_type === c.activity_type));
  const verdictOf = (kind) => catalog.find((c) => c.activity_type === kind);
  return (
    <div className={`card notice ${p.source === "doctor" ? "priority" : "routine"}`}>
      <div className="row-between">
        <strong>Plan to review</strong>
        <span>
          <span className={`badge ${p.source === "doctor" ? "priority" : "routine"}`}>{SOURCE[p.source] || p.source}</span>{" "}
          <span className="badge">{KIND[p.kind] || p.kind}</span>
        </span>
      </div>
      {assessment && <AssessmentView a={assessment} />}
      {p.source === "doctor" ? (
        <p className="small">No AI draft for this patient. Add exercises below and write the instructions.</p>
      ) : (
        <details className="small">
          <summary>Why this draft</summary>
          <p className="pre">{p.reason}</p>
        </details>
      )}
      {p.changes.length > 0 && (
        <table className="small">
          <tbody>
            {p.changes.map((c, i) => (
              <tr key={i}>
                <td>{c.name}</td>
                <td>
                  {dose(c.from)} → {dose(c.to)}
                </td>
                <td className="muted">{c.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="exercises">
        {exercises.map((e, i) => (
          <div key={e.activity_type} className="exercise">
            <div className="row-between">
              <strong className="small">{e.name}</strong>
              <button className="link danger small" onClick={() => remove(i)}>
                Remove
              </button>
            </div>
            <div className="dose small">
              <input type="number" min="1" step="1" value={e.sets}
                     onChange={(ev) => update(i, "sets", parseInt(ev.target.value, 10) || 0)} />
              <span>sets ×</span>
              <input type="number" min="0" step="any" value={e.amount}
                     onChange={(ev) => update(i, "amount", parseFloat(ev.target.value) || 0)} />
              <span>
                {e.unit}
                {verdictOf(e.activity_type)?.per_side && " each side"}
              </span>
              {verdictOf(e.activity_type) && (
                <span className="muted">
                  usual max {verdictOf(e.activity_type).max_sets} × {verdictOf(e.activity_type).max_amount}
                </span>
              )}
            </div>
            <input className="small" value={e.notes} placeholder="Note for the patient (optional)"
                   onChange={(ev) => update(i, "notes", ev.target.value)} />
            {(warnings[e.activity_type] || []).map((w, j) => (
              <div key={j} className="warning">⚠ {w}</div>
            ))}
          </div>
        ))}
        {exercises.length === 0 && <div className="small muted">No exercises yet.</div>}
        <select className="small" value="" onChange={(ev) => add(ev.target.value)} disabled={!unused.length}>
          <option value="">+ Add an exercise…</option>
          {unused.map((c) => (
            <option key={c.activity_type} value={c.activity_type}>
              {c.name}
              {c.verdict === "safe" ? "" : ` (${c.verdict})`}
            </option>
          ))}
        </select>
      </div>

      <label className="sub">
        Instructions for the patient
        <textarea rows={3} value={instructions} onChange={(e) => setInstructions(e.target.value)}
                  placeholder={p.source === "doctor" ? "Write the plan for the patient" : ""} />
      </label>
      {error && <p className="error small">{error}</p>}
      <div className="actions">
        <button className="primary" disabled={!instructions.trim()}
                onClick={() => act("approve", { instructions, exercises: exercises.map(payload), note: note || null })}>
          Approve
        </button>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (required to reject)" />
        <button className="link danger" disabled={!note.trim()} onClick={() => act("reject", { note })}>
          Reject
        </button>
      </div>
    </div>
  );
}

const payload = (e) => ({ activity_type: e.activity_type, sets: e.sets, amount: e.amount, notes: e.notes || "" });

function CaseCard({ c, doctor, onChanged }) {
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  async function close() {
    setError("");
    try {
      await api("POST", `/cases/${c.id}/close`, { doctor_id: doctor.id, note: note || null });
      onChanged();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div className={`card notice ${c.urgency}`}>
      <div className="row-between">
        <strong>Open case</strong>
        <span className={`badge ${c.urgency}`}>{c.urgency}</span>
      </div>
      <div className="small">{c.reason}</div>
      <p className="small pre muted">{c.summary}</p>
      {error && <p className="error small">{error}</p>}
      <div className="actions">
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)" />
        <button className="link" onClick={close}>
          Close case
        </button>
      </div>
    </div>
  );
}
