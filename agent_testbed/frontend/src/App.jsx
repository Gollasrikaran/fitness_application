import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import AgentPanel from "./AgentPanel.jsx";
import PatientPlan from "./PatientPlan.jsx";

// No login. Patient tab: pick a patient and see the plan their doctor
// approved (patients don't chat with the agent). Doctor tab: pick a doctor and
// one of their patients, ask the agent about them, generate and review plans. The
// right-hand panel shows exactly what the agent knows about that patient.

const sexShort = (s) => ({ FEMALE: "F", MALE: "M", OTHER: "O" })[s] || "?";
const pretty = (s) => String(s || "").replace(/_/g, " ").toLowerCase();

function patientLabel(p) {
  const history = p.history.length ? ` · ${p.history.map(pretty).join(", ")}` : "";
  return `#${p.id.slice(0, 8)} · ${p.age} ${sexShort(p.sex)} · ${p.visits} visits · last ${p.last_visit}${history}`;
}

export default function App() {
  const [mode, setMode] = useState("patient");
  const [doctors, setDoctors] = useState([]);
  const [doctorId, setDoctorId] = useState("");
  const [patients, setPatients] = useState([]);
  const [patientId, setPatientId] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  // Bumped after each reply or review, so the side panels reload.
  const [version, setVersion] = useState(0);
  const bump = () => setVersion((v) => v + 1);

  useEffect(() => {
    api("GET", "/doctors").then(setDoctors).catch((e) => setError(`Couldn't load doctors: ${e.message}`));
  }, []);

  // Patient list: everyone (patient mode) or the chosen doctor's patients.
  useEffect(() => {
    if (mode === "doctor" && !doctorId) {
      setPatients([]);
      return;
    }
    const t = setTimeout(() => {
      const params = new URLSearchParams({ limit: "200" });
      if (mode === "doctor") params.set("doctor_id", doctorId);
      if (search.trim()) params.set("search", search.trim());
      api("GET", `/patients?${params}`)
        .then(setPatients)
        .catch((e) => setError(`Couldn't load patients: ${e.message}`));
    }, 300);
    return () => clearTimeout(t);
  }, [mode, doctorId, search]);

  function switchMode(next) {
    setMode(next);
    setPatientId("");
    setSearch("");
  }

  const doctor = doctors.find((d) => d.id === doctorId);
  return (
    <div className="app">
      <header className="topbar">
        <strong>Agent Testbed</strong>
        <div className="toggle">
          {["patient", "doctor"].map((m) => (
            <button key={m} className={mode === m ? "on" : ""} onClick={() => switchMode(m)}>
              {m === "patient" ? "Patient" : "Doctor"}
            </button>
          ))}
        </div>
        <span className="spacer" />
        <span className="small muted">Live clinic data · read-only · no login</span>
      </header>

      <div className="pickers card">
        {mode === "doctor" && (
          <label>
            Doctor
            <select
              value={doctorId}
              onChange={(e) => {
                setDoctorId(e.target.value);
                setPatientId("");
              }}
            >
              <option value="">Choose a doctor…</option>
              {doctors.map((d) => (
                <option key={d.id} value={d.id}>
                  Dr. {d.name}
                  {d.specialization ? ` (${d.specialization})` : ""} · {d.patients} patients
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="grow">
          {mode === "doctor" ? "Patient to ask about" : "View as patient"}
          <select value={patientId} onChange={(e) => setPatientId(e.target.value)} disabled={!patients.length}>
            <option value="">
              {mode === "doctor" && !doctorId ? "Choose a doctor first" : `Choose a patient… (${patients.length})`}
            </option>
            {patients.map((p) => (
              <option key={p.id} value={p.id}>
                {patientLabel(p)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Find by patient id
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="first characters of the id" />
        </label>
      </div>
      {error && <p className="error pad">{error}</p>}
      {mode === "doctor" && doctor && (
        <ReviewQueue doctor={doctor} version={version} current={patientId} onOpen={setPatientId} />
      )}

      {!patientId ? (
        <p className="muted center">
          {mode === "doctor"
            ? "Pick a doctor, then one of their patients, to ask the agent about them."
            : "Pick a patient to see the plan their doctor approved."}
        </p>
      ) : mode === "patient" ? (
        <PatientPlan key={patientId} patientId={patientId} doctors={doctors} />
      ) : (
        <div className="workspace">
          <Chat key={`${doctorId}-${patientId}`} patientId={patientId} doctor={doctor} onReply={bump} />
          <aside className="side">
            <AgentPanel patientId={patientId} doctor={doctor} doctors={doctors} version={version} onChanged={bump} />
            <ContextPanel patientId={patientId} />
          </aside>
        </div>
      )}
    </div>
  );
}

// Drafts this doctor generated that are waiting for review, oldest first.
function ReviewQueue({ doctor, version, current, onOpen }) {
  const [items, setItems] = useState([]);

  useEffect(() => {
    api("GET", `/review-queue?doctor_id=${doctor.id}`)
      .then(setItems)
      .catch(() => setItems([]));
  }, [doctor.id, version]);

  if (!items.length) return null;
  return (
    <div className="card queue">
      <strong className="small">Waiting for your review ({items.length})</strong>
      <div className="queue-items">
        {items.map((q) => (
          <button key={q.proposal_id} className={`queue-item ${q.patient_id === current ? "on" : ""}`}
                  onClick={() => onOpen(q.patient_id)}>
            <span className={`badge sev-${q.severity}`}>{q.source === "doctor" ? "doctor must write" : q.severity}</span>
            <span className="small">
              #{q.patient_id.slice(0, 8)} · {q.age ?? "?"} {sexShort(q.sex)}
            </span>
            <span className="small muted ellipsis">{q.problem || "—"}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function Chat({ patientId, doctor, onReply }) {
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  // The conversation is saved on the server: show it again after a reload.
  useEffect(() => {
    const query = new URLSearchParams({ patient_id: patientId, doctor_id: doctor.id });
    api("GET", `/chat/history?${query}`)
      .then((saved) => setMessages(saved.map((m) => ({ role: m.role, content: m.content }))))
      .catch(() => {});
  }, [patientId, doctor.id]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send(e) {
    e.preventDefault();
    const message = text.trim();
    if (!message) return;
    setText("");
    setBusy(true);
    setMessages((m) => [...m, { role: "user", content: message }]);
    try {
      const out = await api("POST", "/chat", { patient_id: patientId, doctor_id: doctor.id, message });
      setMessages((m) => [...m, { role: "assistant", content: out.reply }]);
      onReply();
    } catch (err) {
      setMessages((m) => [...m, { role: "error", content: err.message }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="chat card">
      <div className="chat-head small muted">
        Dr. {doctor.name} asking about patient #{patientId.slice(0, 8)}
      </div>
      <div className="messages">
        {messages.length === 0 && (
          <p className="muted">Ask about this patient, e.g. “What happened at the last visit?” or “Summarise their BP trend.”</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="content">{m.content}</div>
          </div>
        ))}
        {busy && <div className="msg assistant muted">Thinking…</div>}
        <div ref={endRef} />
      </div>
      <form className="composer" onSubmit={send}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type a message" maxLength={2000} />
        <button className="primary" disabled={busy || !text.trim()}>
          Send
        </button>
      </form>
    </section>
  );
}

function ContextPanel({ patientId }) {
  const [ctx, setCtx] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setCtx(null);
    setError("");
    api("GET", `/patients/${patientId}/context`).then(setCtx).catch((e) => setError(e.message));
  }, [patientId]);

  if (error) return <p className="error">{error}</p>;
  if (!ctx) return <p className="muted">Loading what the agent sees…</p>;

  const { patient, body, conditions, vital_flags, vitals_recent, medicines, care, alerts, history_other } = ctx;
  return (
    <>
      <div className="card">
        <h3>What the agent sees</h3>
        <div className="small">
          {patient.age} y · {pretty(patient.sex)} · {patient.language || "language not recorded"}
        </div>
        <div className="small">
          {body.bmi ? `BMI ${body.bmi} (${body.weight_kg} kg, ${body.height_cm} cm, ${body.measured_on})` : "No height/weight recorded"}
        </div>
        <div className="small muted">
          {care.visits} visits · {care.first_visit} → {care.last_visit}
        </div>
      </div>

      {(alerts.emergencies.length > 0 || alerts.referrals.length > 0) && (
        <Section title="Alerts" tone="alert">
          {alerts.emergencies.map((a, i) => (
            <Row key={`e${i}`}>Emergency on {a.date}: {a.diagnosis || "no diagnosis recorded"}</Row>
          ))}
          {alerts.referrals.map((a, i) => (
            <Row key={`r${i}`}>
              Referral on {a.date}
              {a.to ? ` to ${a.to}` : ""}
              {a.for ? ` for ${a.for}` : ""}
            </Row>
          ))}
        </Section>
      )}

      <Section title="Vital flags (last 5 visits)" empty="No abnormal vitals flagged">
        {vital_flags.map((f, i) => (
          <Row key={i}>
            <span className={`badge ${f.severity === "CRITICAL" ? "emergency" : "priority"}`}>{pretty(f.severity)}</span>{" "}
            {pretty(f.code)} = {f.value} · {f.date}
          </Row>
        ))}
      </Section>

      <Section title="Conditions">
        {conditions.doctor_recorded.map((c, i) => (
          <Row key={`d${i}`}>
            {c.name} <span className="muted">· doctor recorded{c.severity ? `, ${pretty(c.severity)}` : ""}</span>
          </Row>
        ))}
        {conditions.health_history.map((h) => (
          <Row key={h.item}>
            {pretty(h.item)} <span className="muted">· health history{h.notes ? `: ${h.notes}` : ""}</span>
          </Row>
        ))}
        {conditions.long_term_conditions.map((c, i) => (
          <Row key={`l${i}`}>
            {typeof c === "string" ? c : c.name || JSON.stringify(c)} <span className="muted">· long-term list</span>
          </Row>
        ))}
        {!conditions.doctor_recorded.length && !conditions.health_history.length && !conditions.long_term_conditions.length && (
          <Row muted>No recorded conditions</Row>
        )}
        {conditions.recent_diagnoses.length > 0 && <div className="small muted sub">Recent diagnoses</div>}
        {conditions.recent_diagnoses.map((d, i) => (
          <Row key={`x${i}`}>
            {d.date}: {d.confirmed || d.provisional}
            {d.confirmed && d.provisional && d.confirmed !== d.provisional ? ` (provisional: ${d.provisional})` : ""}
          </Row>
        ))}
      </Section>

      <Section title={`Current medicines${medicines.from ? ` (${medicines.from})` : ""}`} empty="No medicines on the latest prescription">
        {medicines.items.map((m, i) => (
          <Row key={i}>
            {m.name} {[m.dosage, m.frequency, m.duration].filter(Boolean).join(" · ")}
          </Row>
        ))}
      </Section>
      {medicines.patient_instructions && (
        <Section title="Doctor's latest instructions">
          <p className="small pre">{medicines.patient_instructions}</p>
        </Section>
      )}

      <Section title="Recent vitals" empty="No vitals recorded">
        {vitals_recent.length > 0 && <VitalsTable rows={vitals_recent} />}
      </Section>

      <Section title="Care">
        <Row>
          Follow-ups: {care.followups?.pending || 0} pending
          {care.followups?.next_due ? ` (next ${care.followups.next_due})` : ""} · {care.followups?.missed || 0} missed
        </Row>
        {care.open_episodes.map((e, i) => (
          <Row key={`ep${i}`}>
            Open episode since {e.since}: {e.chief_complaint || "—"}
          </Row>
        ))}
        {care.open_tasks.map((t, i) => (
          <Row key={`t${i}`}>
            Task: {pretty(t.task_type)} ({pretty(t.status)}
            {t.due_date ? `, due ${t.due_date}` : ""})
          </Row>
        ))}
        {care.recent_complaints.length > 0 && <div className="small muted sub">Recent complaints</div>}
        {care.recent_complaints.slice(0, 5).map((c, i) => (
          <Row key={`c${i}`}>
            {c.date}: {c.complaint}
            {c.duration ? ` (${c.duration})` : ""}
          </Row>
        ))}
      </Section>

      {history_other.length > 0 && (
        <Section title="Other history">
          {history_other.map((h) => (
            <Row key={h.item}>
              {pretty(h.item)}
              {h.notes ? `: ${h.notes}` : ""}
            </Row>
          ))}
        </Section>
      )}

      <details className="card raw">
        <summary className="small">Raw context (JSON)</summary>
        <pre>{JSON.stringify(ctx, null, 2)}</pre>
      </details>
    </>
  );
}

function Section({ title, children, empty, tone }) {
  const hasContent = Array.isArray(children) ? children.flat().some(Boolean) : Boolean(children);
  return (
    <div className={`card ${tone === "alert" ? "notice emergency" : ""}`}>
      <h3>{title}</h3>
      {hasContent ? children : <div className="small muted">{empty || "—"}</div>}
    </div>
  );
}

function Row({ children, muted }) {
  return <div className={`small row-item ${muted ? "muted" : ""}`}>{children}</div>;
}

const VITAL_COLUMNS = [
  ["bp", "BP"],
  ["pulse", "Pulse"],
  ["spo2", "SpO₂"],
  ["sugar_mg_dl", "Sugar"],
  ["weight_kg", "Wt"],
];

function VitalsTable({ rows }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Date</th>
          {VITAL_COLUMNS.map(([, label]) => (
            <th key={label}>{label}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.slice(0, 6).map((r, i) => (
          <tr key={i}>
            <td>{r.date}</td>
            {VITAL_COLUMNS.map(([key]) => (
              <td key={key}>{r[key] ?? (key === "bp" && r.bp_sys ? `${r.bp_sys}/${r.bp_dia}` : "–")}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
