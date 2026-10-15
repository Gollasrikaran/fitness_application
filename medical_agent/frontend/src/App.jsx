import { useEffect, useState } from "react";
import { api } from "./api.js";
import { signOut, supabase, supabaseConfigured } from "./supabase.js";
import Auth, { SetNewPassword } from "./Auth.jsx";
import ProfileForm from "./ProfileForm.jsx";
import PatientHome from "./PatientHome.jsx";
import DoctorHome from "./DoctorHome.jsx";

// Two portals from one app: /doctor... is the doctor portal, everything else
// is the patient app. Each only lets its own kind of account in.
const PORTAL = window.location.pathname.startsWith("/doctor") ? "doctor" : "patient";

export default function App() {
  const [session, setSession] = useState(undefined); // undefined = still checking
  const [user, setUser] = useState(null);
  const [recovering, setRecovering] = useState(false);
  const [portalError, setPortalError] = useState("");
  const [editingProfile, setEditingProfile] = useState(false);

  useEffect(() => {
    if (!supabaseConfigured) return;
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((event, s) => {
      if (event === "PASSWORD_RECOVERY") setRecovering(true); // arrived from a reset-password email
      setSession(s);
    });
    return () => data.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (!session) {
      setUser(null);
      return;
    }
    api("GET", "/auth/me")
      .then(async (me) => {
        if (me.role !== PORTAL) {
          await signOut();
          setPortalError(
            PORTAL === "doctor"
              ? "This is not a doctor account. Patients log in at the patient app."
              : "This is a doctor account. Please use the doctor portal at /doctor."
          );
          return;
        }
        setPortalError("");
        setUser(me);
      })
      .catch((err) => setPortalError(err.message));
  }, [session?.access_token]);

  if (!supabaseConfigured) {
    return (
      <div className="center">
        <div className="card auth">
          <h1>Setup needed</h1>
          <p>
            Add <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> to{" "}
            <code>frontend/.env.local</code>, then restart <code>npm run dev</code>.
          </p>
        </div>
      </div>
    );
  }
  if (session === undefined) return <div className="center muted">Loading…</div>;
  if (recovering) return <SetNewPassword onDone={() => setRecovering(false)} />;
  if (!session || !user) return <Auth portal={PORTAL} error={portalError} />;

  const needsProfile = user.role === "patient" && !user.has_profile;
  return (
    <div className="app">
      <header className="topbar">
        <strong>{PORTAL === "doctor" ? "Vita Doctor Portal" : "Vita Care Agent"}</strong>
        <span className="muted">
          {user.name} · {user.email}
        </span>
        <span className="spacer" />
        {user.role === "patient" && user.has_profile && (
          <button className="link" onClick={() => setEditingProfile(true)}>
            Edit profile
          </button>
        )}
        <button className="link" onClick={signOut}>
          Log out
        </button>
      </header>
      {user.role === "doctor" ? (
        <DoctorHome />
      ) : needsProfile || editingProfile ? (
        <ProfileForm
          onSaved={() => {
            setUser({ ...user, has_profile: true });
            setEditingProfile(false);
          }}
          onCancel={user.has_profile ? () => setEditingProfile(false) : null}
        />
      ) : (
        <PatientHome />
      )}
    </div>
  );
}
