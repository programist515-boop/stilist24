"use client";

import { Button } from "@/components/ui/Button";
import { Card, CardSubtitle, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/cn";
import { formatKibbeFamily, formatSeason } from "@/lib/i18n/analysis";
import type { ProfileSource } from "@/lib/schemas/preferenceQuiz";

interface ResultRevealProps {
  algorithmicKibbe?: string | null;
  algorithmicSeason?: string | null;
  preferenceKibbe?: string | null;
  preferenceSeason?: string | null;
  /** Currently active profile source, if we already know it. */
  currentSource?: ProfileSource;
  onPick: (source: ProfileSource) => void;
  isApplying?: boolean;
}

/**
 * Side-by-side comparison of the algorithmic profile and the preference
 * profile. Both apply buttons kick up to the parent.
 */
export function ResultReveal({
  algorithmicKibbe,
  algorithmicSeason,
  preferenceKibbe,
  preferenceSeason,
  currentSource,
  onPick,
  isApplying,
}: ResultRevealProps) {
  const algoKibbe = algorithmicKibbe ? formatKibbeFamily(algorithmicKibbe) : "—";
  const algoSeason = formatSeason(algorithmicSeason);
  const prefKibbe = preferenceKibbe ? formatKibbeFamily(preferenceKibbe) : "—";
  const prefSeason = formatSeason(preferenceSeason);

  const matches =
    !!algorithmicKibbe &&
    !!preferenceKibbe &&
    algorithmicKibbe.toLowerCase() === preferenceKibbe.toLowerCase() &&
    !!algorithmicSeason &&
    !!preferenceSeason &&
    algorithmicSeason.toLowerCase() === preferenceSeason.toLowerCase();

  return (
    <div className="space-y-6">
      <Card
        className={cn(
          "border-2",
          matches ? "border-emerald-200 bg-emerald-50" : "border-sky-200 bg-sky-50"
        )}
      >
        <CardTitle className={matches ? "text-emerald-900" : "text-sky-900"}>
          {matches
            ? "Алгоритм и ваши лайки совпали"
            : "Сравним два профиля"}
        </CardTitle>
        <CardSubtitle
          className={cn(
            "mt-1",
            matches ? "text-emerald-800" : "text-sky-800"
          )}
        >
          {matches
            ? "Теперь результат подтверждён с двух сторон — можно идти к рекомендациям."
            : "Алгоритм и ваши предпочтения разошлись. Выберите, какой профиль использовать."}
        </CardSubtitle>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <ProfileColumn
          eyebrow="Алгоритм"
          description="Анализ фото: цветотип + тип телосложения."
          kibbe={algoKibbe}
          season={algoSeason}
          tone="neutral"
          isActive={currentSource === "algorithmic"}
          buttonLabel={
            currentSource === "algorithmic"
              ? "Сейчас активен"
              : "Вернуться к автоанализу"
          }
          onClick={() => onPick("algorithmic")}
          disabled={isApplying || currentSource === "algorithmic"}
          isApplying={isApplying && currentSource !== "algorithmic"}
        />
        <ProfileColumn
          eyebrow="По лайкам"
          description="Результат квиза по вашим предпочтениям."
          kibbe={prefKibbe}
          season={prefSeason}
          tone="primary"
          isActive={currentSource === "preference"}
          buttonLabel={
            currentSource === "preference"
              ? "Сейчас активен"
              : "Использовать профиль по лайкам"
          }
          onClick={() => onPick("preference")}
          disabled={isApplying || currentSource === "preference"}
          isApplying={isApplying && currentSource !== "preference"}
        />
      </div>
    </div>
  );
}

function ProfileColumn({
  eyebrow,
  description,
  kibbe,
  season,
  tone,
  isActive,
  buttonLabel,
  onClick,
  disabled,
  isApplying,
}: {
  eyebrow: string;
  description: string;
  kibbe: string;
  season: string;
  tone: "primary" | "neutral";
  isActive: boolean;
  buttonLabel: string;
  onClick: () => void;
  disabled?: boolean;
  isApplying?: boolean;
}) {
  return (
    <Card
      className={cn(
        "flex flex-col",
        tone === "primary" ? "border-ink/20" : ""
      )}
    >
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-[0.14em] text-ink-muted">
          {eyebrow}
        </p>
        {isActive ? <Badge tone="success">Активен</Badge> : null}
      </div>
      <CardSubtitle className="mt-1">{description}</CardSubtitle>
      <dl className="mt-5 space-y-4">
        <div>
          <dt className="text-[11px] font-medium uppercase tracking-wide text-ink-muted">
            Типаж
          </dt>
          <dd className="mt-1 font-display text-2xl tracking-tight text-ink">
            {kibbe}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] font-medium uppercase tracking-wide text-ink-muted">
            Сезон
          </dt>
          <dd className="mt-1 font-display text-2xl tracking-tight text-ink">
            {season}
          </dd>
        </div>
      </dl>
      <div className="mt-6">
        <Button
          variant={tone === "primary" ? "primary" : "secondary"}
          onClick={onClick}
          disabled={disabled}
          loading={isApplying}
          loadingText="Применяем…"
          fullWidth
        >
          {buttonLabel}
        </Button>
      </div>
    </Card>
  );
}
