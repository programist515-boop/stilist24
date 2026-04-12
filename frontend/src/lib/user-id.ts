/**
 * Local "session" identity for the AI Stylist frontend.
 *
 * The backend currently authenticates by reading an `X-User-Id` header
 * (see `app/api/deps.py`). Real JWT auth is on the roadmap; until then we
 * mint a stable UUID per browser and send it on every request so the
 * repository layer has someone to scope rows to.
 */

const KEY = "ai-stylist:user-id";

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
    value
  );
}

function generateUuid(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  // Fallback (RFC4122 v4) for older runtimes
  const bytes = new Uint8Array(16);
  if (typeof crypto !== "undefined" && crypto.getRandomValues) {
    crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * Returns the current browser user id, generating one on first call.
 * Safe to call on the server: returns null when `window` is unavailable.
 */
export function getUserId(): string | null {
  if (typeof window === "undefined") return null;
  let id = window.localStorage.getItem(KEY);
  if (!id || !isUuid(id)) {
    id = generateUuid();
    window.localStorage.setItem(KEY, id);
  }
  return id;
}

export function setUserId(id: string): void {
  if (typeof window === "undefined") return;
  if (!isUuid(id)) return;
  window.localStorage.setItem(KEY, id);
}

export function clearUserId(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(KEY);
}
