import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import AgentPanel from "./AgentPanel.jsx";
import PatientPlan from "./PatientPlan.jsx";

// No login. Patient tab: pick a patient and see the plan their doctor
// approved (patients don't chat with the agent). Doctor tab: pick a doctor and
// one of their patients, ask the agent about them, generate and review plans. The
// right-hand panel shows exactly what the agent knows about that patient.

const sexShort = (s) => ({ FEMALE: "F", MALE: "M", OTHER: "O" })[s] || "?";
const FULL_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const pretty = (s) => String(s || "").replace(/_/g, " ").toLowerCase();

function patientLabel(p) {
  const history = p.history.length ? ` · ${p.history.map(pretty).join(", ")}` : "";
  return `#${p.id.slice(0, 8)} · ${p.age ?? "?"} ${sexShort(p.sex)} · ${p.visits} visits · last ${p.last_visit}${history}`;
}

export default function App() {
  const [mode, setMode] = useState("patient");
  const [doctors, setDoctors] = useState([]);
  const [doctorId, setDoctorId] = useState("");
  const [patients, setPatients] = useState([]);
  const [patientId, setPatientId] = useState("");
  const [search, setSearch] = useState("");
  // The doctors who saw the chosen patient: {patientId, list}.
  const [seenBy, setSeenBy] = useState(null);
  const [error, setError] = useState("");
  // Bumped after each reply or review, so the side panels reload.
  const [version, setVersion] = useState(0);
  const bump = () => setVersion((v) => v + 1);

  useEffect(() => {
    api("GET", "/doctors").then(setDoctors).catch((e) => setError(`Couldn't load doctors: ${e.message}`));
  }, []);

  // Patient list: the chosen doctor's patients, or everyone (patient mode, or
  // a doctor-mode user picking the patient first).
  useEffect(() => {
    const t = setTimeout(() => {
      const params = new URLSearchParams({ limit: "200" });
      if (mode === "doctor" && doctorId) params.set("doctor_id", doctorId);
      if (search.trim()) params.set("search", search.trim());
      api("GET", `/patients?${params}`)
        .then(setPatients)
        .catch((e) => setError(`Couldn't load patients: ${e.message}`));
    }, 300);
    return () => clearTimeout(t);
  }, [mode, doctorId, search]);

  // A full patient id typed in: open that patient straight away.
  useEffect(() => {
    const id = search.trim().toLowerCase();
    if (FULL_ID.test(id)) setPatientId(id);
  }, [search]);

  // Doctor mode: load the chosen patient's doctors, and if the doctor picked
  // isn't one of them, switch to the one who saw the patient most.
  useEffect(() => {
    if (mode !== "doctor" || !patientId) return;
    let live = true;
    api("GET", `/patients/${patientId}/doctors`)
      .then((list) => {
        if (!live) return;
        setSeenBy({ patientId, list });
        // No doctor on any visit (or an unknown id / under 18): any doctor may open the patient (POC).
        if (!list.length) setError(`No doctor is recorded on patient #${patientId.slice(0, 8)}'s visits: choose any doctor above to continue.`);
        else {
          setError("");
          setDoctorId((current) => (list.some((d) => d.id === current) ? current : list[0].id));
        }
      })
      .catch((e) => live && setError(`Couldn't load the patient's doctors: ${e.message}`));
    return () => {
      live = false;
    };
  }, [mode, patientId]);

  function switchMode(next) {
    setMode(next);
    setPatientId("");
    setSearch("");
  }

  const doctor = doctors.find((d) => d.id === doctorId);
  const patientDoctors = seenBy && seenBy.patientId === patientId ? seenBy.list : [];
  const others = doctors.filter((d) => !patientDoctors.some((s) => s.id === d.id));
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
                const id = e.target.value;
                setDoctorId(id);
                if (!patientDoctors.length) setError(""); // a patient with no doctor: keep them, any doctor may open
                else if (!patientDoctors.some((d) => d.id === id)) {
                  setPatientId(""); // another doctor's list: start over
                  setSearch("");
                }
              }}
            >
              <option value="">Choose a doctor…</option>
              {patientDoctors.length > 0 && (
                <optgroup label={`Saw patient #${patientId.slice(0, 8)}`}>
                  {patientDoctors.map((d) => (
                    <option key={d.id} value={d.id}>
                      Dr. {d.name || d.id.slice(0, 8)} · {d.visits} visits with this patient · last {d.last_visit}
                    </option>
                  ))}
                </optgroup>
              )}
              <optgroup label={patientDoctors.length ? "All other doctors" : "All doctors"}>
                {others.map((d) => (
                  <option key={d.id} value={d.id}>
                    Dr. {d.name}
                    {d.specialization ? ` (${d.specialization})` : ""} · {d.patients} patients
                  </option>
                ))}
              </optgroup>
            </select>
          </label>
        )}
        <label className="grow">
          {mode === "doctor" ? "Patient to ask about" : "View as patient"}
          <select value={patientId} onChange={(e) => setPatientId(e.target.value)} disabled={!patients.length && !patientId}>
            <option value="">
              {`Choose a patient… (${patients.length})`}
            </option>
            {patientId && !patients.some((p) => p.id === patientId) && (
              <option value={patientId}>#{patientId.slice(0, 8)} · found by id</option>
            )}
            {patients.map((p) => (
              <option key={p.id} value={p.id}>
                {patientLabel(p)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Find by patient id
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="first characters, or the full id" />
        </label>
      </div>
      {error && <p className="error pad">{error}</p>}
      {mode === "doctor" && doctor && (
        <ReviewQueue doctor={doctor} version={version} current={patientId} onOpen={setPatientId} />
      )}

      {!patientId || (mode === "doctor" && !doctor) ? (
        <p className="muted center">
          {mode === "doctor"
            ? "Pick a doctor then a patient, or paste a full patient id: their doctor is picked for you."
            : "Pick a patient to see the plan their doctor approved."}
        </p>
      ) : mode === "patient" ? (
        <PatientPlan key={patientId} patientId={patientId} />
      ) : (
        <div className="workspace">
          <Chat key={`${doctorId}-${patientId}`} patientId={patientId} doctor={doctor} onReply={bump} />
          <aside className="side">
            {/* key: a new panel per patient, so a late reply for the previous patient can't land here */}
            <AgentPanel key={`${doctorId}-${patientId}`} patientId={patientId} doctor={doctor} doctors={doctors} version={version} onChanged={bump} />
            <ContextPanel key={patientId} patientId={patientId} />
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
  const summary = ctx.clinical_summary;
  const labs = ctx.labs || [];
  return (
    <>
      <div className="card">
        <h3>What the agent sees</h3>
        <div className="small">
          {patient.age} y · {pretty(patient.sex)} · {patient.language || "language not recorded"}
        </div>
        <div className="small">
          {body.bmi
            ? `BMI ${body.bmi} (${body.weight_kg} kg, ${body.height_cm} cm, ${body.measured_on})`
            : body.weight_kg
              ? `Weight ${body.weight_kg} kg (${body.measured_on}) · no BMI: height ${body.height_cm ? `${body.height_cm} cm looks wrong` : "not recorded"}`
              : "No height/weight recorded"}
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

      {summary && (
        <Section title="Clinical flags">
          <Row>
            Exercise:{" "}
            <span className={`badge ${summary.exercise_suitable === false ? "priority" : "routine"}`}>
              {summary.exercise_suitable === false ? "not suitable" : summary.exercise_suitable ? "suitable" : "not assessed"}
            </span>
            {summary.patient_type ? ` · main type ${summary.patient_type}` : ""}
            {summary.exercise_reason && <span className="muted"> · {summary.exercise_reason} (screening, not a safety check)</span>}
          </Row>
          {summary.flags.map((f, i) => (
            <Row key={i}>
              <span className={`badge ${f.level === "high" ? "emergency" : "priority"}`}>{f.level}</span> {f.title}
              {f.evidence && <div className="muted">{f.evidence}</div>}
            </Row>
          ))}
        </Section>
      )}

      {labs.length > 0 && (
        <Section title="Lab results">
          {labs.map((l, i) => (
            <Row key={i}>
              {l.date}: {l.name} {l.value}
              {l.status && (
                <>
                  {" "}
                  <span className={`badge ${labBadge(l.status)}`}>{l.status}</span>
                </>
              )}
            </Row>
          ))}
        </Section>
      )}

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
      {ctx.visits.some((v) => v.patient_instructions) && (
        <Section title="Doctor's notes (latest 3 visits)">
          {ctx.visits
            .filter((v) => v.patient_instructions)
            .slice(0, 3)
            .map((v, i) => (
              <Row key={i}>
                <span className="muted">
                  {v.date}
                  {v.doctor ? ` · Dr. ${v.doctor}` : ""}
                  {i === 0 ? " · latest" : ""}
                </span>
                <div className="pre">{v.patient_instructions}</div>
              </Row>
            ))}
        </Section>
      )}

      <VisitHistory patientId={patientId} />

      <Section title="Recent vitals" empty="No vitals recorded">
        {vitals_recent.length > 0 && <VitalsTable rows={vitals_recent} />}
      </Section>

      <Section title="Care">
        {care.followups ? (
          <Row>
            Follow-ups: {care.followups.pending || 0} pending
            {care.followups.next_due ? ` (next ${care.followups.next_due})` : ""} · {care.followups.missed || 0} missed
            {care.followups.last_missed ? ` (last ${care.followups.last_missed})` : ""}
          </Row>
        ) : (
          <Row>Follow-ups: none recorded</Row>
        )}
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

// Every visit, picked by date: what was recorded at it. For the doctor only:
// the AI reads the latest visits from the context, not this.
function VisitHistory({ patientId }) {
  const [visits, setVisits] = useState(null);
  const [picked, setPicked] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    setVisits(null);
    setPicked(0);
    setError("");
    api("GET", `/patients/${patientId}/visits`)
      .then(setVisits)
      .catch((e) => setError(e.message));
  }, [patientId]);

  if (error) return <p className="error small pad">Couldn't load the visit history: {error}</p>;
  if (!visits?.length) return null;
  const v = visits[picked] || visits[0];
  const vitals = Object.entries(v.vitals || {});
  return (
    <Section title={`Visit history (${visits.length} visits)`}>
      <select value={picked} onChange={(e) => setPicked(Number(e.target.value))}>
        {visits.map((x, i) => (
          <option key={i} value={i}>
            {x.date}
            {x.doctor ? ` · Dr. ${x.doctor}` : ""}
            {x.complaint ? ` · ${x.complaint.slice(0, 40)}` : ""}
          </option>
        ))}
      </select>
      <Row>
        <span className="muted">Complaint: </span>
        {v.complaint || "—"}
        {v.duration ? ` (${v.duration})` : ""}
      </Row>
      {(v.diagnosis_confirmed || v.diagnosis_provisional) && (
        <Row>
          <span className="muted">Diagnosis: </span>
          {v.diagnosis_confirmed || `${v.diagnosis_provisional} (provisional)`}
        </Row>
      )}
      {vitals.length > 0 && (
        <Row>
          <span className="muted">Readings: </span>
          {vitals.map(([k, x]) => `${pretty(k)} ${x}`).join(" · ")}
        </Row>
      )}
      {v.labs?.length > 0 && (
        <Row>
          <span className="muted">Labs: </span>
          {v.labs.map((l) => `${l.name} ${l.value}${l.status ? ` (${l.status})` : ""}`).join(" · ")}
        </Row>
      )}
      {v.medicines?.length > 0 && (
        <Row>
          <span className="muted">Medicines: </span>
          {v.medicines.map((m) => m.name).join(", ")}
        </Row>
      )}
      {v.emergency && <Row>Emergency visit</Row>}
      {v.referral && (
        <Row>
          Referral{v.referral.to ? ` to ${v.referral.to}` : ""}
          {v.referral.for ? ` for ${v.referral.for}` : ""}
        </Row>
      )}
      <Row>
        <span className="muted">Doctor's note: </span>
        <span className="pre">{v.patient_instructions || "—"}</span>
      </Row>
    </Section>
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
  ["hb", "Hb"],
  ["weight_kg", "Wt"],
];

// A lab's status as the report gave it: "Critical (Low)", "High", "Normal", "Unverified (check source)".
function labBadge(status) {
  const s = status.toLowerCase();
  if (s.startsWith("critical")) return "emergency";
  if (s.startsWith("normal")) return "routine";
  if (s.startsWith("unverified")) return "";
  return "priority";
}

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
              <td key={key}>
                {r[key] ??
                  (key === "bp" && r.bp_sys
                    ? `${r.bp_sys}/${r.bp_dia}`
                    : key === "sugar_mg_dl"
                      ? r.fasting_sugar_mg_dl ?? r.nonfasting_sugar_mg_dl ?? "–"
                      : "–")}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
