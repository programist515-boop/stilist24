import { Card } from "@/components/ui/Card";

interface InsightCardProps {
  title: string;
  value?: string | number | null;
  hint?: string;
}

export function InsightCard({ title, value, hint }: InsightCardProps) {
  return (
    <Card padding="sm">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
        {title}
      </p>
      {value !== undefined && value !== null ? (
        <p className="mt-2 font-display text-3xl tracking-tight text-ink">
          {value}
        </p>
      ) : null}
      {hint ? (
        <p className="mt-1 text-xs text-ink-muted">{hint}</p>
      ) : null}
    </Card>
  );
}
