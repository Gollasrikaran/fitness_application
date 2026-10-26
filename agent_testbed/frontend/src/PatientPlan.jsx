import { useEffect, useState } from "react";
import { api } from "./api.js";

// Patient tab: the plan a doctor approved, read-only. Patients don't chat
// with the agent and never see drafts. Large text, one column: many patients
// read it on a small, low-end phone.

export default function PatientPlan({ patientId }) {
  const [plan, setPlan] = useState(undefined);
  const [error, setError] = useState("");

  useEffect(() => {
    api("GET", `/patients/${patientId}/plan`)
      .then((out) => setPlan(out.plan))
      .catch((e) => setError(e.message));
  }, [patientId]);

  if (error) return <p className="error pad">{error}</p>;
  if (plan === undefined) return <p className="patient-plan muted">Loading your plan…</p>;
  if (!plan) return <p className="patient-plan empty">Your doctor hasn't shared a plan yet.</p>;

  return (
    <main className="patient-plan">
      <h1>Your exercise plan</h1>
      <p className="from">
        From {plan.doctor_name ? `Dr. ${plan.doctor_name}` : "your doctor"} · {plan.given_on}
      </p>
      {plan.instructions && <p className="plan-note pre">{plan.instructions}</p>}
      {plan.exercises.map((e, i) => (
        <section key={i} className="ex-card">
          <h2>
            {i + 1}. {e.name}
          </h2>
          <p className="dose">{e.dose}</p>
          {e.rest_seconds && <p className="rest">Rest {e.rest_seconds} seconds between sets</p>}
          {e.notes && <p className="doc-note">Doctor's note: {e.notes}</p>}
          {e.steps.length > 0 && (
            <ol className="steps">
              {e.steps.map((s, j) => (
                <li key={j}>{s}</li>
              ))}
            </ol>
          )}
        </section>
      ))}
    </main>
  );
}
