import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

export const supabaseConfigured = Boolean(url && anonKey);

// The anon (publishable) key is meant to be public. The service role key must
// never appear in this app.
export const supabase = supabaseConfigured ? createClient(url, anonKey) : null;

// supabase-js keeps the session when its call to Supabase fails (e.g. a
// network error), so "Log out" would silently do nothing. If that happens,
// drop the stored session ourselves and reload: the app starts logged out.
export async function signOut() {
  const { error } = await supabase.auth.signOut();
  if (error) {
    localStorage.removeItem(supabase.auth.storageKey);
    window.location.reload();
  }
}
