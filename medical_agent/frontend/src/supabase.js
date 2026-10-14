import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

export const supabaseConfigured = Boolean(url && anonKey);

// The anon (publishable) key is meant to be public. The service role key must
// never appear in this app.
export const supabase = supabaseConfigured ? createClient(url, anonKey) : null;
