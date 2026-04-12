import { Card, CardSubtitle, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import type { TryOnJob } from "@/lib/schemas";

const STATUS_TONE: Record<
  string,
  "success" | "warning" | "danger" | "neutral"
> = {
  succeeded: "success",
  pending: "warning",
  failed: "danger",
};

const STATUS_LABEL: Record<string, string> = {
  succeeded: "Готово",
  pending: "В процессе",
  failed: "Ошибка",
};

interface TryOnResultProps {
  job: TryOnJob;
  onReset?: () => void;
}

export function TryOnResult({ job, onReset }: TryOnResultProps) {
  const tone = STATUS_TONE[job.status] ?? "neutral";
  const label = STATUS_LABEL[job.status] ?? job.status;
  const isPending = job.status === "pending";

  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <div>
          <CardTitle>Результат примерки</CardTitle>
          <CardSubtitle className="mt-1 break-all font-mono text-[11px] text-ink-muted">
            {job.job_id}
          </CardSubtitle>
        </div>
        <Badge tone={tone}>{label}</Badge>
      </div>

      <div className="mt-5">
        {job.result_image_url ? (
          <div className="overflow-hidden rounded-2xl border border-canvas-border bg-accent-soft">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={job.result_image_url}
              alt="Результат примерки"
              className="h-auto w-full object-cover"
            />
          </div>
        ) : job.error_message ? (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            {job.error_message}
          </div>
        ) : isPending ? (
          <div className="flex items-center gap-3 rounded-xl border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            <Spinner className="h-4 w-4 border-amber-700 border-t-transparent" />
            <span>Алгоритм ещё обрабатывает запрос. Обновите, чтобы проверить статус.</span>
          </div>
        ) : (
          <div className="rounded-xl border border-canvas-border bg-accent-soft/50 px-4 py-3 text-sm text-ink-muted">
            На этот раз изображение не вернулось.
          </div>
        )}
      </div>

      {job.note ? (
        <p className="mt-4 text-xs text-ink-muted">{job.note}</p>
      ) : null}

      {onReset ? (
        <div className="mt-5 flex justify-end">
          <Button variant="secondary" size="sm" onClick={onReset}>
            Попробовать ещё
          </Button>
        </div>
      ) : null}
    </Card>
  );
}
