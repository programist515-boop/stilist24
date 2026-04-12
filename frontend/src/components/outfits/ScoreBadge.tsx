import { Badge } from "@/components/ui/Badge";

export function ScoreBadge({ label, value }: { label: string; value: number }) {
  return (
    <Badge tone="neutral">
      <span className="capitalize text-ink-muted">{label}</span>
      <span className="ml-1.5 font-semibold text-ink">
        {Math.round(value * 100)}
      </span>
    </Badge>
  );
}
