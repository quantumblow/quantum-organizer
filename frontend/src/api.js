const JSON_HEADERS = { "Content-Type": "application/json" };

async function request(url, options = {}) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text.slice(0, 300)}`);
  }
  return resp.json();
}

export function listRoots() {
  return request("/api/v1/roots");
}

export function browse(path) {
  const query = path ? `?path=${encodeURIComponent(path)}` : "";
  return request(`/api/v1/browse${query}`);
}

export function createPlan(payload) {
  return request("/api/v1/plans", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function fetchItems(planId, params) {
  const query = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== "") query.set(k, v);
  });
  return request(`/api/v1/plans/${planId}/items?${query.toString()}`);
}

export function applyPlan(planId, payload) {
  return request(`/api/v1/plans/${planId}/apply`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function undoOp(opId) {
  return request(`/api/v1/ops/${opId}/undo`, { method: "POST" });
}

export function fetchOp(opId) {
  return request(`/api/v1/ops/${opId}`);
}
