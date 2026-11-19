const BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8001";

// The backend and the patient API are on Render's free plan: after a quiet
// spell they sleep and take up to a minute to wake. A GET that fails while
// they wake (no answer at all, or 502/503/504) is tried again a few times.
// POSTs are never repeated: "Generate plan" would run the AI twice.
const WAKE_RETRIES_MS = [5000, 10000, 20000];
const WAKING = new Set([502, 503, 504]);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function send(method, path, body) {
  return fetch(BASE + path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export async function api(method, path, body) {
  const retries = method === "GET" ? WAKE_RETRIES_MS : [];
  let res;
  for (let attempt = 0; ; attempt++) {
    try {
      res = await send(method, path, body);
      if (!WAKING.has(res.status) || attempt >= retries.length) break;
    } catch (e) {
      // "Failed to fetch": the server didn't answer (asleep, or no network).
      if (attempt >= retries.length) {
        throw new Error("The server didn't answer. Please refresh the page.");
      }
    }
    await sleep(retries[attempt]);
  }
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
