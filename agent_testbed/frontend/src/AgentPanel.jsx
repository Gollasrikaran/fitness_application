import { useEffect, useState } from "react";
import { api } from "./api.js";

// Doctor tab: the agent's own data for one patient (temporary database): the
// approved plan, the draft waiting for review, and any open doctor case. The
// draft and case are reviewed here.

const KIND = { starter: "First plan", easier: "Easier plan", update: "Conditions changed" };
const dose = (d) => (d ? `${d.sets} × ${d.amount}` : "—");

export default function AgentPanel({ patientId, doctor, doctors, version, onChanged }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api("GET", `/patients/${patientId}/agent`)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [patientId, version]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return null;
  const doctorName = (id) => doctors.find((d) => d.id === id)?.name || "a doctor";
  const { plan, pending, open_case } = data;

  return (
    <>
      {open_case && <CaseCard c={open_case} doctor={doctor} onChanged={onChanged} />}
      {pending && <PendingCard p={pending} doctor={doctor} onChanged={onChanged} />}
      <div className="card">
        <h3>Exercise plan</h3>
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

function PendingCard({ p, doctor, onChanged }) {
  const [instructions, setInstructions] = useState(p.instructions);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  async function act(path, body) {
    setError("");
    try {
      await api("POST", `/proposals/${p.id}/${path}`, { doctor_id: doctor.id, ...body });
      onChanged();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div className="card notice priority">
      <div className="row-between">
        <strong>Plan to review</strong>
        <span className={`badge ${p.source === "doctor" ? "priority" : "routine"}`}>{KIND[p.kind]}</span>
      </div>
      <p className="small pre">{p.reason}</p>
      {p.patient_note && <p className="small">Patient said: “{p.patient_note}”</p>}
      {p.changes.length > 0 && (
        <table>
          <tbody>
            {p.changes.map((c, i) => (
              <tr key={i}>
                <td>{c.name}</td>
                <td>{dose(c.from)} → {dose(c.to)}</td>
                <td className="small muted">{c.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {p.exercises.map((e, i) => (
        <div key={i} className="small row-item">
          • {e.name}: {e.sets} × {e.amount} {e.unit} {e.notes && <span className="muted">({e.notes})</span>}
        </div>
      ))}
      <label className="sub">
        Instructions for the patient
        <textarea
          rows={3}
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          placeholder={p.source === "doctor" ? "The rules couldn't draft this one: write the plan" : ""}
        />
      </label>
      {error && <p className="error small">{error}</p>}
      <div className="actions">
        <button className="primary" onClick={() => act("approve", { instructions, note: note || null })}>
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
