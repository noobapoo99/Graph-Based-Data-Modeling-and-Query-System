// Uses an environment-provided backend URL because production static builds cannot rely on a dev proxy.
const BASE = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

// Resolves an API path because development should use Vite's relative `/api` proxy while non-dev builds may need an absolute backend URL.
function resolveApiUrl(path) {
  // Normalizes relative input so all callers can pass either `api/query` or `/api/query`.
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  // Keeps browser requests same-origin during Vite dev so Docker and local runs both use the proxy cleanly.
  if (import.meta.env.DEV) {
    return normalizedPath;
  }

  // Falls back to an absolute backend URL outside Vite dev because there is no dev proxy in that mode.
  return `${BASE}${normalizedPath}`;
}

// Parses the response body because failed API calls should still surface the server's most useful error text.
async function parseResponseBody(response) {
  const responseText = await response.text();

  // Returns `null` for empty bodies because some errors provide status codes without JSON payloads.
  if (!responseText) {
    return null;
  }

  try {
    return JSON.parse(responseText);
  } catch (error) {
    // Falls back to the raw text because not every upstream error is guaranteed to be valid JSON.
    return responseText;
  }
}

// Builds a readable error because the UI needs something actionable when the server returns a non-OK status.
function buildApiError(response, payload) {
  if (payload && typeof payload === "object") {
    if (typeof payload.detail === "string") {
      return new Error(payload.detail);
    }

    if (typeof payload.answer === "string") {
      return new Error(payload.answer);
    }

    if (typeof payload.message === "string") {
      return new Error(payload.message);
    }
  }

  if (typeof payload === "string" && payload.trim()) {
    return new Error(payload);
  }

  return new Error(`Request failed with status ${response.status}.`);
}

// Executes one API request because keeping fetch logic in one place makes the UI easier to maintain and debug.
export async function apiFetch(path, options = {}) {
  const response = await fetch(resolveApiUrl(path), {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.headers || {}),
    },
  });

  const payload = await parseResponseBody(response);

  if (!response.ok) {
    throw buildApiError(response, payload);
  }

  return payload;
}

// Sends a natural-language query because the chat panel should not need to know any HTTP details.
export async function sendQuery(query, sessionId) {
  return apiFetch("/api/query", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      query,
      session_id: sessionId,
    }),
  });
}
