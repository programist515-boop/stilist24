"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchIdentityDNA, type IdentityDNA } from "@/lib/api/identityDna";
import { usePersona } from "@/providers/PersonaProvider";
import { Card, CardSubtitle, CardTitle } from "@/components/ui/Card";

/** Карточка «Кто ты стилистически» — ассоциативный слой Фазы 8.
 *
 * Показывается после того как пользователь прошёл анализ и у его
 * активной персоны есть определённый подтип Kibbe. До этого — скрыта
 * (backend вернёт пустой subtype, мы возвращаем ``null``).
 *
 * Дисклеймер про community-консенсус celebrity-примеров вшит в подвал
 * карточки — плановая правка из обновлённого раздела Фазы 8 в
 * ``plans/2026-04-21-каталог-фич-из-отчёта-типажа.md``.
 */
export function IdentityDNACard() {
  const { activePersonaId } = usePersona();
  const { data, isLoading, error } = useQuery<IdentityDNA, Error>({
    queryKey: ["identity-dna", activePersonaId],
    queryFn: fetchIdentityDNA,
    enabled: activePersonaId !== null,
    staleTime: 60_000,
  });

  if (isLoading) return null;
  if (error) return null;
  if (!data || !data.subtype) return null;

  return (
    <Card>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <CardTitle>Кто ты стилистически</CardTitle>
        <span className="text-xs uppercase tracking-[0.18em] text-ink-muted">
          {data.display_name_ru}
          {data.display_name_en ? ` · ${data.display_name_en}` : ""}
        </span>
      </div>

      {data.motto && (
        <p className="mt-3 font-display text-xl leading-snug tracking-tight">
          «{data.motto}»
        </p>
      )}

      {data.associations.length > 0 && (
        <div className="mt-5 flex flex-wrap gap-2">
          {data.associations.map((tag) => (
            <span
              key={tag}
              className="rounded-full bg-accent-soft px-3 py-1 text-xs font-medium text-ink"
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      {data.philosophy && (
        <p className="mt-5 whitespace-pre-line text-sm leading-relaxed text-ink-muted">
          {data.philosophy}
        </p>
      )}

      {data.key_principles.length > 0 && (
        <div className="mt-5">
          <CardSubtitle>Ваши опоры в одежде</CardSubtitle>
          <ul className="mt-3 space-y-2">
            {data.key_principles.map((p) => (
              <li
                key={p}
                className="flex gap-2 rounded-xl bg-canvas-card p-3 text-sm"
              >
                <span className="text-accent" aria-hidden>
                  ●
                </span>
                <span>{p}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.celebrity_examples.length > 0 && (
        <div className="mt-5">
          <CardSubtitle>Ориентиры</CardSubtitle>
          <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {data.celebrity_examples.map((c) => (
              <li key={c.name} className="text-ink">
                {c.name}
                {c.era && (
                  <span className="ml-1 text-xs text-ink-muted">({c.era})</span>
                )}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-ink-muted">
            Примеры — по мнению community, не официальные вердикты Дэвида Кибби.
            Это ориентиры для визуального понимания типажа, не «быть как они».
          </p>
        </div>
      )}
    </Card>
  );
}
