import { useEffect, useState } from "react";
import { api } from "./api.js";
import { ExerciseRows, PatientFacts, PlanExercises, ProgressTable, toPayload } from "./doctorParts.jsx";

// Plans drafted by the backend's rules. None reaches the patient until a
// doctor approves it here, as drafted or edited.

const KIND = {
  starter: "First plan",
  easier: "Easier plan (patient asked)",
  update: "Conditions changed",
};

export default function PlanReviews({ switcher }) {
  const [status, setStatus] = useState("pending");
  const [rows, setRows] = useState([]);
  const [selected, setSelected] = useState(null);

  const load = () => api("GET", `/doctor/proposals?status=${status}`).then(setRows);
  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [status]);

  return (
    <div className="doctor">
      <aside className="card queue">
        {switcher}
        <div className="tabs">
          {["pending", "approved", "rejected", "all"].map((s) => (
            <button key={s} className={s === status ? "tab on" : "tab"} onClick={() => setStatus(s)}>
              {s}
            </button>
          ))}
        </div>
        {rows.length === 0 && <p className="muted small">No plans here.</p>}
        {rows.map((p) => (
          <button key={p.id} className={"case-row" + (selected === p.id ? " on" : "")} onClick={() => setSelected(p.id)}>
            <span className={`badge ${p.source === "doctor" ? "priority" : "routine"}`}>{KIND[p.kind]}</span>
            <strong>{p.patient}</strong>
            <span className="small muted">{p.reason.split("\n")[0]}</span>
            <span className="small muted">
              {new Date(p.created_at).toLocaleString()}
              {status === "all" && ` · ${p.status}`}
            </span>
          </button>
        ))}
      </aside>
      <section className="detail">
        {selected ? (
          <ProposalDetail key={selected} id={selected} onDone={load} />
        ) : (
          <p className="muted center">Select a plan to review.</p>
        )}
      </section>
    </div>
  );
}

const editable = (exercises) =>
  exercises.map(({ activity_type, sets, amount, notes }) => ({ activity_type, sets, amount, notes: notes || "" }));
const dose = (d) => (d ? `${d.sets} × ${d.amount}` : "—");

function ProposalDetail({ id, onDone }) {
  const [p, setP] = useState(null);
  const [instructions, setInstructions] = useState("");
  const [rows, setRows] = useState([]);
  const [rejectNote, setRejectNote] = useState("");
  const [error, setError] = useState("");

  const reload = () =>
    api("GET", `/doctor/proposals/${id}`).then((data) => {
      setP(data);
      setInstructions(data.instructions);
      setRows(editable(data.exercises));
    });
  useEffect(() => {
    reload();
  }, [id]);
  if (!p) return <p className="muted">Loading…</p>;

  const ctx = p.patient_context;
  const pending = p.status === "pending";

  async function act(path, body) {
    setError("");
    try {
      await api("POST", `/doctor/proposals/${id}/${path}`, body);
      await reload();
      onDone();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <>
      <div className="card">
        <div className="row-between">
          <h2>{p.patient}</h2>
          <span className={`badge ${p.source === "doctor" ? "priority" : "routine"}`}>{KIND[p.kind]}</span>
        </div>
        <PatientFacts ctx={ctx} />
        <h3>{p.source === "doctor" ? "Why the rules couldn't draft this" : "How the rules drafted this"}</h3>
        <p className="pre">{p.reason}</p>
        {p.patient_note && (
          <>
            <h3>The patient says</h3>
            <p className="pre">{p.patient_note}</p>
          </>
        )}
        {p.changes.length > 0 && (
          <>
            <h3>Changes</h3>
            <table>
              <thead>
                <tr>
                  <th>Exercise</th>
                  <th>Before</th>
                  <th>After</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {p.changes.map((c, i) => (
                  <tr key={i}>
                    <td>{c.name}</td>
                    <td>{dose(c.from)}</td>
                    <td>{dose(c.to)}</td>
                    <td className="small muted">{c.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
      {p.based_on_plan && (
        <div className="card">
          <h3>Current plan (stays until you approve)</h3>
          <p className="pre">{p.based_on_plan.instructions}</p>
          <PlanExercises exercises={p.based_on_plan.exercises} />
        </div>
      )}
      <div className="card">
        <h3>Progress</h3>
        <ProgressTable progress={ctx.progress} />
      </div>
      {pending ? (
        <form
          className="card"
          onSubmit={(e) => {
            e.preventDefault();
            act("approve", { instructions, exercises: toPayload(rows) });
          }}
        >
          <h3>{p.source === "doctor" ? "Write the plan" : "Review the plan"}</h3>
          <p className="small muted">Edit anything you like. The patient sees it only after you approve.</p>
          <textarea
            rows={4}
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            placeholder="Advice and instructions for the patient"
            required
          />
          <ExerciseRows rows={rows} setRows={setRows} approved={ctx.approved_exercises} />
          {error && <p className="error">{error}</p>}
          <div className="actions">
            <button className="primary">Approve and send to patient</button>
          </div>
          <div className="row reject">
            <input
              value={rejectNote}
              onChange={(e) => setRejectNote(e.target.value)}
              placeholder="Reason for rejecting (required)"
            />
            <button
              type="button"
              className="link danger"
              disabled={!rejectNote.trim()}
              onClick={() => act("reject", { note: rejectNote })}
            >
              Reject
            </button>
          </div>
        </form>
      ) : (
        <div className="card">
          <h3>{p.approved_plan ? `Approved by Dr. ${p.approved_plan.doctor}` : `Draft ${p.status}`}</h3>
          {p.review_note && <p className="pre">Note: {p.review_note}</p>}
          <p className="pre">{(p.approved_plan || p).instructions}</p>
          <PlanExercises exercises={(p.approved_plan || p).exercises} />
        </div>
      )}
    </>
  );
}
