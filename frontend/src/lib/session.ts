/**
 * Session facade for the AI Stylist frontend.
 *
 * Three pieces of locally-stored session state live here:
 *
 * 1. **Access token** — issued by ``POST /auth/signup`` or ``/auth/login``.
 *    When present, every API request sends ``Authorization: Bearer <token>``
 *    and the browser UUID is no longer needed.
 *
 * 2. **Active persona id** — which persona the user is currently working
 *    as. Defaults to the primary (auto-selected by the backend when the
 *    header is omitted), but the switcher in the nav bar lets the user
 *    pick any persona belonging to the account.
 *
 * 3. **Browser UUID** (``user-id.ts``, kept for backward-compat) —
 *    legacy path for dev: when there is no access token, the backend
 *    falls back to resolving by ``X-User-Id`` header.
 */

const ACCESS_TOKEN_KEY = "ai-stylist:access-token";
const ACTIVE_PERSONA_KEY = "ai-stylist:active-persona-id";

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
    value
  );
}

// ---------------- access token ------------------------------------------

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function setAccessToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ACCESS_TOKEN_KEY, token);
}

export function clearAccessToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return getAccessToken() !== null;
}

// ---------------- active persona ----------------------------------------

export function getActivePersonaId(): string | null {
  if (typeof window === "undefined") return null;
  const id = window.localStorage.getItem(ACTIVE_PERSONA_KEY);
  return id && isUuid(id) ? id : null;
}

export function setActivePersonaId(id: string): void {
  if (typeof window === "undefined") return;
  if (!isUuid(id)) return;
  window.localStorage.setItem(ACTIVE_PERSONA_KEY, id);
}

export function clearActivePersonaId(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(ACTIVE_PERSONA_KEY);
}

// ---------------- aggregate logout --------------------------------------

/** Remove everything session-related from localStorage. */
export function clearSession(): void {
  clearAccessToken();
  clearActivePersonaId();
}
