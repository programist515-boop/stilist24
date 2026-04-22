"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/Skeleton";
import { Badge } from "@/components/ui/Badge";
import { QuizCard } from "./QuizCard";
import { SwipeStack, SwipeStackProgress } from "./SwipeStack";
import { getTryonStatus } from "@/lib/api/preferenceQuiz";
import type {
  IdentityTryOnCandidate,
  TryOnJobStatus,
  VoteAction,
} from "@/lib/schemas/preferenceQuiz";
import { formatKibbeFamily } from "@/lib/i18n/analysis";

interface TryOnRevealProps {
  sessionId: string;
  candidates: IdentityTryOnCandidate[];
  onVote: (candidate: IdentityTryOnCandidate, action: VoteAction) => void;
  onAllVoted: () => void;
}

/**
 * Polls `/preference-quiz/identity/{id}/tryon-status` every 2 seconds until
 * all jobs reach a terminal state (succeeded / failed). Once ready, swaps
 * the loader for a `SwipeStack` of the rendered try-on images.
 */
export function TryOnReveal({
  sessionId,
  candidates,
  onVote,
  onAllVoted,
}: TryOnRevealProps) {
  const jobIds = useMemo(
    () => candidates.map((c) => c.tryon_job_id),
    [candidates]
  );

  const allDone = (jobs: TryOnJobStatus[]): boolean =>
    jobs.length >= jobIds.length &&
    jobs.every((j) => j.status === "succeeded" || j.status === "failed");

  const statusQuery = useQuery({
    queryKey: ["preference-quiz", "identity", sessionId, "tryon-status"],
    queryFn: () => getTryonStatus(sessionId),
    enabled: jobIds.length > 0,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 2000;
      return allDone(data.jobs) ? false : 2000;
    },
  });

  const jobs = statusQuery.data?.jobs ?? [];
  const ready = allDone(jobs);

  // Build ready cards only from jobs that actually rendered. Failures are
  // silently skipped — the user never sees a dead slot.
  const readyCards = useMemo(() => {
    if (!ready) return [];
    const byJobId = new Map(jobs.map((j) => [j.job_id, j]));
    return candidates
      .map((c) => {
        const job = byJobId.get(c.tryon_job_id);
        if (!job || job.status !== "succeeded" || !job.result_image_url) {
          return null;
        }
        return {
          id: c.candidate_id,
          candidate: c,
          imageUrl: job.result_image_url,
        };
      })
      .filter((x): x is {
        id: string;
        candidate: IdentityTryOnCandidate;
        imageUrl: string;
      } => x !== null);
  }, [ready, jobs, candidates]);

  const [votedCount, setVotedCount] = useState(0);
  const [likeCount, setLikeCount] = useState(0);

  // Re-arm counters whenever the batch of ready cards changes identity.
  useEffect(() => {
    setVotedCount(0);
    setLikeCount(0);
  }, [readyCards.length]);

  if (!ready) {
    const doneJobs = jobs.filter(
      (j) => j.status === "succeeded" || j.status === "failed"
    ).length;
    return (
      <div className="mx-auto flex w-full max-w-sm flex-col items-center gap-4">
        <Badge tone="info">Готовим примерки — {doneJobs}/{jobIds.length}</Badge>
        <div className="grid w-full grid-cols-3 gap-3">
          {candidates.map((c) => {
            const job = jobs.find((j) => j.job_id === c.tryon_job_id);
            const status = job?.status ?? "pending";
            return (
              <div
                key={c.candidate_id}
                className="overflow-hidden rounded-2xl border border-canvas-border bg-canvas-card"
              >
                <Skeleton className="aspect-[3/4] w-full rounded-none" />
                <div className="p-2 text-center text-[10px] text-ink-muted">
                  <p className="font-medium text-ink">
                    {formatKibbeFamily(c.subtype)}
                  </p>
                  <p className="mt-0.5">
                    {status === "pending"
                      ? "в очереди"
                      : status === "running"
                        ? "рендерим…"
                        : status === "failed"
                          ? "ошибка"
                          : "готово"}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
        <p className="text-xs text-ink-muted">
          Обычно занимает 20–40 секунд. Можно не закрывать вкладку.
        </p>
      </div>
    );
  }

  if (readyCards.length === 0) {
    return (
      <div className="mx-auto max-w-sm rounded-2xl border border-amber-200 bg-amber-50 px-4 py-5 text-sm text-amber-900">
        Ни одна примерка не сгенерировалась. Используем результаты первого
        этапа без корректировки.
      </div>
    );
  }

  const handleVote = (
    card: (typeof readyCards)[number],
    action: VoteAction
  ) => {
    onVote(card.candidate, action);
    setVotedCount((n) => n + 1);
    if (action === "like") setLikeCount((n) => n + 1);
  };

  return (
    <div className="space-y-6">
      <SwipeStack
        cards={readyCards}
        onVote={({ card, action }) => handleVote(card, action)}
        onFinished={() => onAllVoted()}
        renderCard={({ card, depth, overlay, onVote: vote, disabled }) => (
          <QuizCard
            imageUrl={card.imageUrl}
            title={formatKibbeFamily(card.candidate.subtype)}
            subtitle={card.candidate.subtitle ?? "Как это смотрится на вас?"}
            depth={depth}
            overlay={overlay}
            disabled={disabled}
            onVote={vote}
          />
        )}
      />
      <SwipeStackProgress
        total={readyCards.length}
        done={votedCount}
        likes={likeCount}
      />
    </div>
  );
}
