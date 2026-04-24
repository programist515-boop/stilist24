"use client";

import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/layout/PageHeader";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { ReferenceLookCard } from "@/components/reference-looks/ReferenceLookCard";
import { getReferenceLooks } from "@/lib/api/referenceLooks";

/**
 * Страница «Образы по твоему типажу».
 *
 * Показывает референсные луки, собранные из гардероба пользователя.
 * Подтип активно определяется style_profile_resolver на бэке
 * (учитывает как алгоритм, так и preference-quiz).
 */
export default function ReferenceLooksPage() {
  const query = useQuery({
    queryKey: ["reference-looks"],
    queryFn: getReferenceLooks,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });

  return (
    <>
      <PageHeader
        eyebrow="Твой типаж"
        title="Образы по твоему типажу"
        subtitle="Референсные луки, собранные из твоего гардероба. Слоты, которые мы не смогли закрыть, — подсказки для шопинга."
      />

      {query.isPending ? (
        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-64 w-full" />
          ))}
        </div>
      ) : null}

      {query.isError ? (
        <ErrorState
          title="Не удалось загрузить референсы"
          error={query.error}
          onRetry={() => query.refetch()}
        />
      ) : null}

      {query.isSuccess && !query.data.subtype ? (
        <EmptyState
          title="Подтип ещё не определён"
          hint="Пройди анализ или квиз — и мы покажем референсные луки для твоего типажа."
        />
      ) : null}

      {query.isSuccess && query.data.looks.length === 0 && query.data.subtype ? (
        <EmptyState
          title={`Для подтипа «${query.data.subtype}» пока нет референсов`}
          hint="Контент по этому подтипу ещё не подготовлен — следи за обновлениями."
        />
      ) : null}

      {query.isSuccess && query.data.looks.length > 0 ? (
        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          {query.data.looks.map((look) => (
            <ReferenceLookCard key={look.look_id} look={look} />
          ))}
        </div>
      ) : null}
    </>
  );
}
