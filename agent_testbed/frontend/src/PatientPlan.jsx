import { useEffect, useState } from "react";
import { api } from "./api.js";

// Patient tab: the plan a doctor approved, read-only. Patients don't chat
// with the agent and never see drafts.

export default function PatientPlan({ patientId, doctors }) {
  const [plan, setPlan] = useState(undefined);
  const [error, setError] = useState("");

  useEffect(() => {
    api("GET", `/patients/${patientId}/plan`)
      .then((out) => setPlan(out.plan))
      .catch((e) => setError(e.message));
  }, [patientId]);

  if (error) return <p className="error pad">{error}</p>;
  if (plan === undefined) return <p className="muted center">Loading your plan…</p>;
  if (!plan) return <p className="muted center">Your doctor hasn't shared a plan yet.</p>;

  const doctorName = doctors.find((d) => d.id === plan.doctor_id)?.name;
  return (
    <section className="card patient-plan">
      <h2>Your exercise plan</h2>
      <div className="small muted">
        From Dr. {doctorName || "your doctor"} · {plan.given_on}
      </div>
      {plan.instructions && <p className="pre">{plan.instructions}</p>}
      <ol>
        {plan.exercises.map((e, i) => (
          <li key={i}>
            <strong>{e.name}</strong>: {e.sets} × {e.amount} {e.unit}
            {e.notes && <div className="small muted">{e.notes}</div>}
          </li>
        ))}
      </ol>
    </section>
  );
}
