import type { ReactNode } from "react";
import { Spinner } from "./Spinner";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";

interface QueryStateProps {
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  isEmpty?: boolean;
  emptyTitle?: string;
  emptyHint?: string;
  emptyAction?: ReactNode;
  onRetry?: () => void;
  /** Optional skeleton to render in place of the spinner. */
  loadingFallback?: ReactNode;
  children: ReactNode;
}

/**
 * Single source of truth for query lifecycle UI. Either pass a custom
 * `loadingFallback` (skeleton) or fall back to the default spinner.
 */
export function QueryState({
  isLoading,
  isError,
  error,
  isEmpty,
  emptyTitle = "Пока ничего нет",
  emptyHint = "Как только появятся данные, они отобразятся здесь.",
  emptyAction,
  onRetry,
  loadingFallback,
  children,
}: QueryStateProps) {
  if (isLoading) {
    if (loadingFallback) return <>{loadingFallback}</>;
    return (
      <div className="flex h-40 items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (isError) {
    return <ErrorState error={error} onRetry={onRetry} />;
  }
  if (isEmpty) {
    return (
      <EmptyState title={emptyTitle} hint={emptyHint} action={emptyAction} />
    );
  }
  return <>{children}</>;
}
