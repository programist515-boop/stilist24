/**
 * Beta telemetry client.
 *
 * Two entry points:
 *
 * * ``trackEvent`` — fire-and-forget funnel tracking. We never want a
 *   failed beacon to surface to the UI (no skeleton, no toast), so the
 *   function swallows all errors. Use ``trackEvent('page_viewed', {path})``
 *   from any screen.
 * * ``submitBetaFeedback`` — surfaces errors because the caller is a
 *   form that needs to tell the user whether the send succeeded.
 *
 * Both hit the ``/events/*`` routes added in the closed-beta plan — see
 * ``ai-stylist-starter/app/api/routes/events.py``.
 */

import { apiRequest } from "./client";

export async function trackEvent(
  event_type: string,
  payload: Record<string, unknown> = {}
): Promise<void> {
  try {
    await apiRequest("/events/track", {
      method: "POST",
      json: { event_type, payload },
    });
  } catch {
    // Telemetry must never break the UI. Swallow network/validation
    // failures — we'll notice missing events server-side instead.
  }
}

export type BetaFeedbackInput = {
  message: string;
  contact?: string;
  context?: Record<string, unknown>;
};

export async function submitBetaFeedback(input: BetaFeedbackInput): Promise<void> {
  await apiRequest("/events/beta-feedback", {
    method: "POST",
    json: {
      message: input.message,
      contact: input.contact || null,
      context: input.context ?? {},
    },
  });
}
