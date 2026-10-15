import { useEffect, useState } from "react";
import { api } from "./api.js";

// Pieces shared by the case view and the plan-review view.

export function PatientFacts({ ctx }) {
  const p = ctx.patient;
  return (
    <>
      <div className="small muted">
        {p.age} y · {p.sex} · {p.height_cm ?? "?"} cm · {p.weight_kg ?? "?"} kg
        {p.bmi && ` · BMI ${p.bmi}`} · {p.experience}
      </div>
      <div className="small">Conditions: {ctx.conditions.map((x) => x.name).join(", ") || "none"}</div>
    </>
  );
}

export function ProgressTable({ progress }) {
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

export function PlanExercises({ exercises }) {
  return exercises.map((e, i) => (
    <div key={i} className="small">
      • {e.name}: {e.sets} × {e.amount} {e.unit} {e.notes && `(${e.notes})`}
    </div>
  ));
}

// Editable exercise rows: [{activity_type, sets, amount, notes}]. `approved`
// is the patient's safety-grid list, so anything outside it is labelled.
export function ExerciseRows({ rows, setRows, approved }) {
  const [all, setAll] = useState([]);
  useEffect(() => {
    api("GET", "/exercises").then(setAll);
  }, []);
  const safe = new Set(approved.map((e) => e.activity_type));
  const update = (i, k, v) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));

  return (
    <>
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
    </>
  );
}

export const toPayload = (rows) => rows.map((r) => ({ ...r, sets: Number(r.sets), amount: Number(r.amount) }));
