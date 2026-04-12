"use client";

import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/layout/PageHeader";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { QueryState } from "@/components/ui/QueryState";
import { Skeleton } from "@/components/ui/Skeleton";
import { WardrobeItemCard } from "@/components/wardrobe/WardrobeItemCard";
import { WardrobeUploader } from "@/components/wardrobe/WardrobeUploader";
import { listWardrobeItems } from "@/lib/api/wardrobe";

function WardrobeGridSkeleton() {
  return (
    <div className="grid gap-4 grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {Array.from({ length: 6 }).map((_, i) => (
        <div
          key={i}
          className="overflow-hidden rounded-2xl border border-canvas-border bg-canvas-card"
        >
          <Skeleton className="aspect-square rounded-none" />
          <div className="space-y-2 p-4">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-3 w-24" />
          </div>
        </div>
      ))}
    </div>
  );
}

function pluralizeItems(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return "вещь";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "вещи";
  return "вещей";
}

export default function WardrobePage() {
  const query = useQuery({
    queryKey: ["wardrobe"],
    queryFn: listWardrobeItems,
  });

  const count = query.data?.length ?? 0;

  return (
    <>
      <PageHeader
        eyebrow="Гардероб"
        title="Всё, что у вас есть"
        subtitle="Добавляйте по одной вещи. Подбор образов учитывает теги, цвет и силуэт."
      />

      <WardrobeUploader />

      <section>
        <SectionHeader
          title="Ваш гардероб"
          description={
            count > 0
              ? `${count} ${pluralizeItems(count)}`
              : "Здесь будут появляться добавленные вещи."
          }
        />
        <QueryState
          isLoading={query.isLoading}
          isError={query.isError}
          error={query.error}
          onRetry={() => query.refetch()}
          isEmpty={!!query.data && query.data.length === 0}
          emptyTitle="Пока ничего нет"
          emptyHint="Загрузите первую вещь выше, чтобы начать."
          loadingFallback={<WardrobeGridSkeleton />}
        >
          <div className="grid gap-4 grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {query.data?.map((item) => (
              <WardrobeItemCard key={item.id} item={item} />
            ))}
          </div>
        </QueryState>
      </section>
    </>
  );
}
