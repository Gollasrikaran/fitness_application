import { useEffect, useState } from "react";
import { api } from "./api.js";

export default function ProfileForm({ onSaved, onCancel }) {
  const [conditions, setConditions] = useState([]);
  const [form, setForm] = useState({ age: "", sex: "female", height_cm: "", weight_kg: "", experience: "beginner" });
  const [picked, setPicked] = useState([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api("GET", "/conditions").then(setConditions);
    api("GET", "/profile").then((p) => {
      if (!p) return;
      setForm({ age: p.age, sex: p.sex, height_cm: p.height_cm ?? "", weight_kg: p.weight_kg ?? "", experience: p.experience });
      setPicked(p.conditions);
    });
  }, []);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const toggle = (code) => setPicked(picked.includes(code) ? picked.filter((c) => c !== code) : [...picked, code]);
  const num = (v) => (v === "" ? null : Number(v));

  async function submit(e) {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      await api("PUT", "/profile", {
        ...form,
        age: Number(form.age),
        height_cm: num(form.height_cm),
        weight_kg: num(form.weight_kg),
        conditions: picked,
      });
      onSaved();
    } catch (err) {
      setError(err.message === "Failed to fetch" ? "Can't reach the server. Is the backend running?" : err.message);
    } finally {
      setSaving(false);
    }
  }

  const groups = [
    ["supported", "Conditions"],
    ["refer", "These need a doctor to review first"],
  ];
  return (
    <form className="card profile" onSubmit={submit}>
      <h2>Your profile</h2>
      <p className="muted">The assistant uses this to keep its advice safe for you.</p>
      <div className="row">
        <label>
          Age
          <input type="number" min="18" max="100" value={form.age} onChange={set("age")} required />
        </label>
        <label>
          Sex
          <select value={form.sex} onChange={set("sex")}>
            <option value="female">Female</option>
            <option value="male">Male</option>
            <option value="other">Other</option>
          </select>
        </label>
        <label>
          Height (cm)
          <input type="number" step="any" min="100" max="250" value={form.height_cm} onChange={set("height_cm")} />
        </label>
        <label>
          Weight (kg)
          <input type="number" step="any" min="25" max="300" value={form.weight_kg} onChange={set("weight_kg")} />
        </label>
        <label>
          Activity level
          <select value={form.experience} onChange={set("experience")}>
            <option value="beginner">Beginner</option>
            <option value="intermediate">Intermediate</option>
            <option value="active">Active</option>
          </select>
        </label>
      </div>
      {groups.map(([bucket, title]) => (
        <fieldset key={bucket}>
          <legend>{title}</legend>
          <div className="chips">
            {conditions
              .filter((c) => c.bucket === bucket && c.code !== "none")
              .map((c) => (
                <label key={c.code} className={"chip" + (picked.includes(c.code) ? " on" : "")}>
                  <input type="checkbox" checked={picked.includes(c.code)} onChange={() => toggle(c.code)} />
                  {c.name}
                </label>
              ))}
          </div>
        </fieldset>
      ))}
      <p className="muted small">Leave everything unticked if none apply.</p>
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button className="primary" disabled={saving}>{saving ? "Saving…" : "Save"}</button>
        {onCancel && (
          <button type="button" className="link" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
