import { useState } from "react";
import { supabase } from "./supabase.js";

// portal: "patient" (login, signup, forgot password) or
//         "doctor"  (login and forgot password only — accounts are created by an admin)
export default function Auth({ portal, error: outerError }) {
  const [mode, setMode] = useState("login"); // login | signup | forgot
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const here = window.location.origin + window.location.pathname;

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setInfo("");
    try {
      if (mode === "login") {
        const { error } = await supabase.auth.signInWithPassword({ email: form.email, password: form.password });
        if (error) throw error;
        // App.jsx takes over from here via onAuthStateChange.
      } else if (mode === "signup") {
        const { data, error } = await supabase.auth.signUp({
          email: form.email,
          password: form.password,
          options: { data: { name: form.name }, emailRedirectTo: here },
        });
        if (error) throw error;
        if (!data.session) {
          setInfo(`We've sent a verification link to ${form.email}. Open it to activate your account, then log in.`);
          setMode("login");
        }
      } else {
        const { error } = await supabase.auth.resetPasswordForEmail(form.email, { redirectTo: here });
        if (error) throw error;
        setInfo(`If an account exists for ${form.email}, a password reset link is on its way.`);
        setMode("login");
      }
    } catch (err) {
      setError(friendly(err.message));
    } finally {
      setBusy(false);
    }
  }

  const title = portal === "doctor" ? "Doctor portal" : "Vita Care Agent";
  return (
    <div className="center">
      <form className="card auth" onSubmit={submit}>
        <h1>{title}</h1>
        <p className="muted">
          {mode === "login" ? "Log in to continue" : mode === "signup" ? "Create your account" : "Reset your password"}
        </p>
        {mode === "signup" && (
          <label>
            Name
            <input value={form.name} onChange={set("name")} required />
          </label>
        )}
        <label>
          Email
          <input type="email" value={form.email} onChange={set("email")} required />
        </label>
        {mode !== "forgot" && (
          <label>
            Password
            <input type="password" value={form.password} onChange={set("password")} minLength={8} required />
          </label>
        )}
        {info && <p className="good small">{info}</p>}
        {(error || outerError) && <p className="error">{error || outerError}</p>}
        <button className="primary" disabled={busy}>
          {busy ? "Please wait…" : mode === "login" ? "Log in" : mode === "signup" ? "Sign up" : "Send reset link"}
        </button>
        {mode === "login" && (
          <button type="button" className="link" onClick={() => setMode("forgot")}>
            Forgot password?
          </button>
        )}
        {portal === "patient" && mode !== "forgot" && (
          <button type="button" className="link" onClick={() => setMode(mode === "login" ? "signup" : "login")}>
            {mode === "login" ? "New here? Create an account" : "Already have an account? Log in"}
          </button>
        )}
        {mode === "forgot" && (
          <button type="button" className="link" onClick={() => setMode("login")}>
            Back to login
          </button>
        )}
        <a className="small muted switch" href={portal === "doctor" ? "/" : "/doctor"}>
          {portal === "doctor" ? "Patient? Go to the patient app" : "Doctor? Go to the doctor portal"}
        </a>
      </form>
    </div>
  );
}

export function SetNewPassword({ onDone }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  async function submit(e) {
    e.preventDefault();
    const { error } = await supabase.auth.updateUser({ password });
    if (error) setError(friendly(error.message));
    else onDone();
  }
  return (
    <div className="center">
      <form className="card auth" onSubmit={submit}>
        <h1>Choose a new password</h1>
        <label>
          New password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="primary">Save password</button>
      </form>
    </div>
  );
}

function friendly(message) {
  if (/email not confirmed/i.test(message)) return "Please verify your email first — check your inbox for the link.";
  if (/invalid login credentials/i.test(message)) return "Wrong email or password.";
  return message;
}
