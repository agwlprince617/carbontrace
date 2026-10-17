export class LocalConnectionError extends Error {
  constructor(timedOut = false) {
    super(`${timedOut ? "The local CarbonTrace server took too long to respond." : "Cannot reach the local CarbonTrace server."} In VS Code, run “CarbonTrace: start local app”, then reconnect below. Your draft is still here. This interface sends no model calls.`);
    this.name = "LocalConnectionError";
    this.reconnect = true;
  }
}

export async function requestLocal(path, options = {}, timeoutMs = 10000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    let response;
    try {
      response = await fetch(path, { ...options, signal: controller.signal });
    } catch {
      throw new LocalConnectionError(controller.signal.aborted);
    }
    let payload;
    try {
      payload = await response.json();
    } catch {
      if (controller.signal.aborted) throw new LocalConnectionError(true);
      throw new Error(`The local server returned an unreadable response (HTTP ${response.status}). Check that CarbonTrace is running on this address, then try again.`);
    }
    if (!response.ok) {
      const detail = Array.isArray(payload?.detail) ? payload.detail.map((item) => item.msg).join("; ") : payload?.detail;
      throw new Error(typeof detail === "string" ? detail : `Request failed (HTTP ${response.status}).`);
    }
    return payload;
  } finally {
    clearTimeout(timer);
  }
}
