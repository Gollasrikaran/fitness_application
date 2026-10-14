import { supabase } from "./supabase.js";

const BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export async function api(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  // supabase-js keeps the session fresh; always send the current access token.
  const { data } = await supabase.auth.getSession();
  if (data.session) headers.Authorization = `Bearer ${data.session.access_token}`;
  const res = await fetch(BASE + path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const json = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = json?.detail;
    const message = Array.isArray(detail)
      ? detail.map((d) => `${d.loc?.slice(-1)[0]}: ${d.msg}`).join(", ")
      : detail || `Request failed (${res.status})`;
    const err = new Error(message);
    err.status = res.status;
    throw err;
  }
  return json;
}
