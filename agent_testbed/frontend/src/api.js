const BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8001";

export async function api(method, path, body) {
  const res = await fetch(BASE + path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const json = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = json?.detail;
    const message = Array.isArray(detail)
      ? detail.map((d) => `${d.loc?.slice(-1)[0]}: ${d.msg}`).join(", ")
      : detail || `Request failed (${res.status})`;
    throw new Error(message);
  }
  return json;
}
