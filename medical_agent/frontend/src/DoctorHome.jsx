import { useEffect, useState } from "react";
import { api } from "./api.js";
import { ExerciseRows, PatientFacts, PlanExercises, ProgressTable, toPayload } from "./doctorParts.jsx";
import PlanReviews from "./PlanReviews.jsx";

export default function DoctorHome() {
  const [view, setView] = useState("cases");
  const [pending, setPending] = useState(0);

  useEffect(() => {
    const load = () =>
      api("GET", "/doctor/proposals")
        .then((rows) => setPending(rows.length))
        .catch(() => {});
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [view]);

  const switcher = (
    <div className="views">
      <button className={view === "cases" ? "view on" : "view"} onClick={() => setView("cases")}>
        Cases
      </button>
      <button className={view === "plans" ? "view on" : "view"} onClick={() => setView("plans")}>
        Plan reviews{pending > 0 && <span className="count">{pending}</span>}
      </button>
    </div>
  );
  return view === "cases" ? <Cases switcher={switcher} /> : <PlanReviews switcher={switcher} />;
}

function Cases({ switcher }) {
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
        {switcher}
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
  return (
    <>
      <div className="card">
        <div className="row-between">
          <h2>{c.patient}</h2>
          <span className={`badge ${c.urgency}`}>{c.urgency}</span>
        </div>
        <PatientFacts ctx={ctx} />
        <div className="small muted">Status: {c.status.replace("_", " ")}</div>
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
          <PlanExercises exercises={pl.exercises} />
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

function PlanForm({ caseId, approved, onDone }) {
  const [instructions, setInstructions] = useState("");
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setError("");
    try {
      await api("POST", `/doctor/cases/${caseId}/plan`, { instructions, exercises: toPayload(rows) });
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
      <ExerciseRows rows={rows} setRows={setRows} approved={approved} />
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
