import { Button } from "./Button";

interface ErrorStateProps {
  title?: string;
  error?: unknown;
  onRetry?: () => void;
  className?: string;
}

function readMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return "Что-то пошло не так.";
}

/**
 * Inline error card. Lives inside the page where the request failed and
 * surfaces a Try again action when one is available. Use for query errors
 * and mutation errors that block a flow.
 */
export function ErrorState({
  title = "Не удалось выполнить запрос",
  error,
  onRetry,
  className,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={
        "rounded-2xl border border-red-200 bg-red-50 px-6 py-5 " +
        (className ?? "")
      }
    >
      <h3 className="text-sm font-semibold text-red-900">{title}</h3>
      <p className="mt-1 text-sm text-red-800">{readMessage(error)}</p>
      {onRetry ? (
        <div className="mt-4">
          <Button size="sm" variant="secondary" onClick={onRetry}>
            Попробовать ещё раз
          </Button>
        </div>
      ) : null}
    </div>
  );
}
