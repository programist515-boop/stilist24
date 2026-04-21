"use client";

/**
 * Floating beta-feedback button.
 *
 * Anchored to the bottom-right, stacked above the MobileNav on small
 * screens (``bottom-20`` keeps it clear of the 16h nav) and closer to
 * the corner on desktop (``lg:bottom-6``). One click opens a small
 * dialog with a textarea and an optional contact field; submission
 * posts to ``POST /events/beta-feedback`` (see
 * ``ai-stylist-starter/app/api/routes/events.py``).
 *
 * Everything is controlled state — no portal, no custom modal library.
 * The overlay is a plain fixed div that blocks clicks to the rest of
 * the app; ESC and the close button dismiss it.
 */

import { useEffect, useId, useState } from "react";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { submitBetaFeedback } from "@/lib/api/events";

type Status = "idle" | "sending" | "sent" | "error";

export function FeedbackButton() {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [contact, setContact] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const pathname = usePathname();
  const messageId = useId();
  const contactId = useId();

  // Dismiss with ESC so the dialog behaves like a real modal.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = message.trim();
    if (!trimmed) return;
    setStatus("sending");
    try {
      await submitBetaFeedback({
        message: trimmed,
        contact: contact.trim() || undefined,
        context: { path: pathname ?? null },
      });
      setStatus("sent");
      setMessage("");
      setContact("");
      // Auto-close after a short confirmation window so the user can
      // see the "sent" state.
      window.setTimeout(() => {
        setOpen(false);
        setStatus("idle");
      }, 1200);
    } catch {
      setStatus("error");
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setStatus("idle");
          setOpen(true);
        }}
        className="fixed bottom-20 right-4 z-40 inline-flex h-11 items-center gap-2 rounded-full bg-ink px-4 text-sm font-medium text-canvas shadow-lg transition-colors hover:bg-ink-soft lg:bottom-6"
        aria-label="Оставить фидбек"
      >
        <span aria-hidden>✎</span>
        <span>Фидбек</span>
      </button>

      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-ink/40 p-4 backdrop-blur-sm sm:items-center"
          role="dialog"
          aria-modal="true"
          aria-labelledby={`${messageId}-title`}
          onClick={(e) => {
            if (e.target === e.currentTarget) setOpen(false);
          }}
        >
          <form
            onSubmit={handleSubmit}
            className="w-full max-w-md space-y-4 rounded-2xl border border-canvas-border bg-canvas-card p-5 shadow-xl"
          >
            <div>
              <h2
                id={`${messageId}-title`}
                className="font-display text-lg tracking-tight"
              >
                Поделиться впечатлением
              </h2>
              <p className="mt-1 text-xs text-ink-muted">
                Что зацепило, что раздражает, что не понятно. Всё читаем лично.
              </p>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor={messageId}>Сообщение</Label>
              <textarea
                id={messageId}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={5}
                maxLength={2000}
                required
                autoFocus
                placeholder="Например: «не понял, как добавить юбку»"
                className="w-full rounded-xl border border-canvas-border bg-canvas px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:ring-2 focus:ring-ink"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor={contactId}>
                Telegram или email (по желанию)
              </Label>
              <Input
                id={contactId}
                value={contact}
                onChange={(e) => setContact(e.target.value)}
                maxLength={200}
                placeholder="@username или name@example.com"
              />
              <p className="text-xs text-ink-muted">
                Оставьте, если готовы ответить на 1–2 вопроса.
              </p>
            </div>

            {status === "error" ? (
              <p className="text-sm text-red-700">
                Не удалось отправить. Проверьте интернет и попробуйте ещё раз.
              </p>
            ) : null}
            {status === "sent" ? (
              <p className="text-sm text-emerald-700">
                Спасибо! Получили.
              </p>
            ) : null}

            <div className="flex items-center justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() => setOpen(false)}
              >
                Отмена
              </Button>
              <Button
                type="submit"
                disabled={!message.trim() || status === "sending" || status === "sent"}
                loading={status === "sending"}
                loadingText="Отправляем…"
              >
                Отправить
              </Button>
            </div>
          </form>
        </div>
      ) : null}
    </>
  );
}
