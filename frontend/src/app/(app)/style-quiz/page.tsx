"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api/client";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardSubtitle, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/layout/PageHeader";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { ColorDraperyCard } from "@/components/style-quiz/ColorDraperyCard";
import { IdentityMatchStep } from "@/components/style-quiz/IdentityMatchStep";
import { QuizCard } from "@/components/style-quiz/QuizCard";
import {
  SwipeStack,
  SwipeStackProgress,
} from "@/components/style-quiz/SwipeStack";
import { ResultReveal } from "@/components/style-quiz/ResultReveal";
import { loadLastAnalysis } from "@/lib/local-store";
import { trackEvent } from "@/lib/api/events";
import {
  advanceToSeason,
  completeColorQuiz,
  completeIdentityQuiz,
  getWardrobeMatch,
  setActiveProfileSource,
  startColorQuiz,
  startIdentityQuiz,
  voteColor,
  voteIdentity,
} from "@/lib/api/preferenceQuiz";
import type {
  ActiveProfileSourceResponse,
  ColorCompleteResponse,
  ColorFamilyCandidate,
  ColorSeasonCandidate,
  IdentityCompleteResponse,
  IdentityLookMatch,
  IdentityStockCandidate,
  ProfileSource,
} from "@/lib/schemas/preferenceQuiz";
import { formatKibbeFamily, formatSeason } from "@/lib/i18n/analysis";

type Step =
  | "intro"
  | "identity-stock"
  | "identity-match"
  | "color-family"
  | "color-season"
  | "result";

export default function StyleQuizPage() {
  const [step, setStep] = useState<Step>("intro");

  // identity state
  const [identitySessionId, setIdentitySessionId] = useState<string | null>(
    null
  );
  const [stockCandidates, setStockCandidates] = useState<
    IdentityStockCandidate[]
  >([]);
  const [stockLikeCount, setStockLikeCount] = useState(0);
  const [stockVotedCount, setStockVotedCount] = useState(0);
  const [matchLooks, setMatchLooks] = useState<IdentityLookMatch[]>([]);
  const [identityResult, setIdentityResult] =
    useState<IdentityCompleteResponse | null>(null);

  // color state
  const [colorSessionId, setColorSessionId] = useState<string | null>(null);
  const [familyCandidates, setFamilyCandidates] = useState<
    ColorFamilyCandidate[]
  >([]);
  const [familyLikeCount, setFamilyLikeCount] = useState(0);
  const [familyVotedCount, setFamilyVotedCount] = useState(0);
  const [seasonCandidates, setSeasonCandidates] = useState<
    ColorSeasonCandidate[]
  >([]);
  const [seasonVotedCount, setSeasonVotedCount] = useState(0);
  const [colorResult, setColorResult] = useState<ColorCompleteResponse | null>(
    null
  );

  // switch state
  const [currentSource, setCurrentSource] = useState<ProfileSource>(
    "algorithmic"
  );

  const queryClient = useQueryClient();

  // cached algorithmic result from the last /analyze run — used in the
  // final comparison screen.
  const algorithmic = useMemo(() => {
    const a = loadLastAnalysis();
    return {
      kibbe: a?.kibbe?.main_type ?? null,
      season: a?.color?.season_top_1 ?? null,
    };
  }, []);

  // ---------------- mutations ----------------

  const startIdentity = useMutation({
    mutationFn: startIdentityQuiz,
    onSuccess: (res) => {
      setIdentitySessionId(res.session_id);
      setStockCandidates(res.candidates);
      setStockLikeCount(0);
      setStockVotedCount(0);
      setStep("identity-stock");
      trackEvent("preference_quiz_started", { quiz: "identity" });
    },
  });

  const voteIdentityMutation = useMutation({
    mutationFn: async (input: {
      candidateId: string;
      action: "like" | "dislike";
    }) => {
      if (!identitySessionId) throw new Error("Нет активной сессии квиза");
      await voteIdentity(
        identitySessionId,
        input.candidateId,
        input.action
      );
    },
  });

  const wardrobeMatchMutation = useMutation({
    mutationFn: async () => {
      if (!identitySessionId) throw new Error("Нет активной сессии");
      return getWardrobeMatch(identitySessionId);
    },
    onSuccess: (res) => {
      setMatchLooks(res.looks);
      setStep("identity-match");
      trackEvent("style_quiz_stock_completed", {
        looks: res.looks.length,
      });
    },
  });

  const completeIdentityMutation = useMutation({
    mutationFn: async () => {
      if (!identitySessionId) throw new Error("Нет активной сессии");
      return completeIdentityQuiz(identitySessionId);
    },
    onSuccess: (res) => {
      setIdentityResult(res);
      trackEvent("preference_quiz_identity_completed", {
        winner: res.winner,
        confidence: res.confidence,
      });
      // Funnel-алиас: identity-фаза завершена.
      trackEvent("style_quiz_tryon_completed", {
        winner: res.winner,
        confidence: res.confidence,
      });
    },
  });

  const startColor = useMutation({
    mutationFn: startColorQuiz,
    onSuccess: (res) => {
      setColorSessionId(res.session_id);
      setFamilyCandidates(res.candidates);
      setFamilyLikeCount(0);
      setFamilyVotedCount(0);
      setStep("color-family");
      trackEvent("preference_quiz_started", { quiz: "color" });
    },
  });

  const voteColorMutation = useMutation({
    mutationFn: async (input: {
      candidateId: string;
      action: "like" | "dislike";
    }) => {
      if (!colorSessionId) throw new Error("Нет активной сессии цветового квиза");
      await voteColor(colorSessionId, input.candidateId, input.action);
    },
  });

  const advanceToSeasonMutation = useMutation({
    mutationFn: async () => {
      if (!colorSessionId) throw new Error("Нет активной сессии");
      return advanceToSeason(colorSessionId);
    },
    onSuccess: (res) => {
      setSeasonCandidates(res.candidates);
      setSeasonVotedCount(0);
      setStep("color-season");
    },
  });

  const completeColorMutation = useMutation({
    mutationFn: async () => {
      if (!colorSessionId) throw new Error("Нет активной сессии");
      return completeColorQuiz(colorSessionId);
    },
    onSuccess: (res) => {
      setColorResult(res);
      setStep("result");
      trackEvent("preference_quiz_color_completed", {
        winner: res.winner,
        confidence: res.confidence,
      });
    },
  });

  const applySourceMutation = useMutation<
    ActiveProfileSourceResponse,
    unknown,
    ProfileSource
  >({
    mutationFn: (source) => setActiveProfileSource(source),
    onSuccess: (res) => {
      setCurrentSource(res.source);
      trackEvent("preference_quiz_source_applied", { source: res.source });
      // При переключении профиля рекомендации/today/gap-analysis
      // должны перезапроситься — старые висят в TanStack-кэше иначе.
      // Wardrobe не трогаем — он не зависит от профиля.
      void queryClient.invalidateQueries({ queryKey: ["today"] });
      void queryClient.invalidateQueries({ queryKey: ["outfits"] });
      void queryClient.invalidateQueries({ queryKey: ["recommendations"] });
      void queryClient.invalidateQueries({ queryKey: ["gap-analysis"] });
      void queryClient.invalidateQueries({ queryKey: ["identity-dna"] });
      // Funnel-алиас: пользователь активировал профиль по лайкам.
      if (res.source === "preference") {
        trackEvent("preference_profile_activated", { source: res.source });
      }
    },
  });

  // after identity is completed — auto-start color quiz
  useEffect(() => {
    if (
      identityResult &&
      step === "identity-match" &&
      !colorSessionId &&
      !startColor.isPending
    ) {
      startColor.mutate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identityResult, step]);

  // ---------------- rendering ----------------

  return (
    <>
      <PageHeader
        eyebrow="Квиз"
        title="Уточним стиль по вашим лайкам"
        subtitle="Лайкайте образы и палитры — в конце сравним результат квиза с тем, что определил алгоритм."
      />

      <Stepper current={step} />

      {step === "intro" ? (
        <IntroStep
          onStart={() => startIdentity.mutate()}
          isPending={startIdentity.isPending}
          error={startIdentity.error}
        />
      ) : null}

      {step === "identity-stock" ? (
        <IdentityStockStep
          candidates={stockCandidates}
          likeCount={stockLikeCount}
          votedCount={stockVotedCount}
          onVote={(card, action) => {
            voteIdentityMutation.mutate({
              candidateId: card.candidate_id,
              action,
            });
            setStockVotedCount((n) => n + 1);
            if (action === "like") setStockLikeCount((n) => n + 1);
          }}
          onAdvance={() => wardrobeMatchMutation.mutate()}
          canAdvance={stockLikeCount >= 3}
          advancing={wardrobeMatchMutation.isPending}
          error={wardrobeMatchMutation.error}
        />
      ) : null}

      {step === "identity-match" ? (
        <IdentityMatchStep
          looks={matchLooks}
          onComplete={() => completeIdentityMutation.mutate()}
          completing={completeIdentityMutation.isPending}
          error={completeIdentityMutation.error}
        />
      ) : null}

      {step === "color-family" ? (
        <ColorFamilyStep
          candidates={familyCandidates}
          likeCount={familyLikeCount}
          votedCount={familyVotedCount}
          onVote={(card, action) => {
            voteColorMutation.mutate({
              candidateId: card.candidate_id,
              action,
            });
            setFamilyVotedCount((n) => n + 1);
            if (action === "like") setFamilyLikeCount((n) => n + 1);
          }}
          onAdvance={() => advanceToSeasonMutation.mutate()}
          canAdvance={familyLikeCount >= 1}
          advancing={advanceToSeasonMutation.isPending}
          error={advanceToSeasonMutation.error}
        />
      ) : null}

      {step === "color-season" ? (
        <ColorSeasonStep
          candidates={seasonCandidates}
          votedCount={seasonVotedCount}
          onVote={(card, action) => {
            voteColorMutation.mutate({
              candidateId: card.candidate_id,
              action,
            });
            setSeasonVotedCount((n) => n + 1);
          }}
          onAllVoted={() => completeColorMutation.mutate()}
          completing={completeColorMutation.isPending}
          error={completeColorMutation.error}
        />
      ) : null}

      {step === "result" ? (
        <ResultStep
          algorithmicKibbe={algorithmic.kibbe}
          algorithmicSeason={algorithmic.season}
          preferenceKibbe={identityResult?.winner ?? null}
          preferenceSeason={colorResult?.winner ?? null}
          currentSource={currentSource}
          onPick={(src) => applySourceMutation.mutate(src)}
          isApplying={applySourceMutation.isPending}
          error={applySourceMutation.error}
        />
      ) : null}
    </>
  );
}

/* ---------------- steps ---------------- */

function Stepper({ current }: { current: Step }) {
  const steps: Array<{ key: Step; label: string }> = [
    { key: "intro", label: "Старт" },
    { key: "identity-stock", label: "Типаж" },
    { key: "identity-match", label: "Из гардероба" },
    { key: "color-family", label: "Палитра" },
    { key: "color-season", label: "Сезон" },
    { key: "result", label: "Итог" },
  ];
  const currentIdx = steps.findIndex((s) => s.key === current);

  return (
    <ol className="flex flex-wrap items-center gap-2 text-[11px] font-medium uppercase tracking-wide">
      {steps.map((s, i) => {
        const isActive = s.key === current;
        const isDone = i < currentIdx;
        return (
          <li key={s.key} className="flex items-center gap-2">
            <Badge
              tone={isActive ? "info" : isDone ? "success" : "neutral"}
              className="whitespace-nowrap"
            >
              {i + 1}. {s.label}
            </Badge>
            {i < steps.length - 1 ? (
              <span className="text-ink-muted">·</span>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

function IntroStep({
  onStart,
  isPending,
  error,
}: {
  onStart: () => void;
  isPending: boolean;
  error: unknown;
}) {
  return (
    <div className="space-y-6">
      <Card>
        <CardTitle>Как это работает</CardTitle>
        <CardSubtitle className="mt-1">
          5 минут, без загрузок. В конце — сравнение с автоанализом.
        </CardSubtitle>
        <ol className="mt-5 space-y-3 text-sm text-ink">
          <li>
            <strong className="font-semibold">1. Типаж.</strong> Лайкайте образы
            — алгоритм поймёт, какая эстетика вам ближе. На втором шаге мы
            покажем, как собрать эти образы из вашего гардероба.
          </li>
          <li>
            <strong className="font-semibold">2. Из гардероба.</strong>{" "}
            Для каждого лайкнутого образа — что у вас уже есть, чего не хватает,
            и что докупить, чтобы повторить его.
          </li>
          <li>
            <strong className="font-semibold">3. Палитра.</strong> 4 карточки
            со сменой оттенков у лица — выберите семью сезонов, где вы
            выглядите живее. Потом уточним сезон внутри.
          </li>
          <li>
            <strong className="font-semibold">4. Результат.</strong> Сравниваем
            с тем, что показал автоматический анализ. Если предпочтения
            отличаются — одной кнопкой переключим профиль.
          </li>
        </ol>
      </Card>

      {error ? (
        <ErrorState
          title="Не удалось запустить квиз"
          error={error}
          onRetry={onStart}
        />
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={onStart} loading={isPending} size="lg">
          Начать квиз
        </Button>
        <Link href="/analyze">
          <Button variant="ghost" size="lg">
            Вернуться к анализу
          </Button>
        </Link>
      </div>
    </div>
  );
}

function IdentityStockStep({
  candidates,
  likeCount,
  votedCount,
  onVote,
  onAdvance,
  canAdvance,
  advancing,
  error,
}: {
  candidates: IdentityStockCandidate[];
  likeCount: number;
  votedCount: number;
  onVote: (
    card: IdentityStockCandidate,
    action: "like" | "dislike"
  ) => void;
  onAdvance: () => void;
  canAdvance: boolean;
  advancing: boolean;
  error: unknown;
}) {
  if (candidates.length === 0) {
    return (
      <EmptyState
        title="Нет карточек"
        hint="Контент для квиза пока не загружен. Попробуйте позже."
      />
    );
  }

  // useMemo so the array reference is stable across re-renders triggered
  // by parent state updates after a vote (counters, mutation flags).
  // Without it, SwipeStack saw a fresh `cards` prop each render and
  // reset its internal `remaining`, sending the just-voted card back
  // to the top — the stack appeared frozen after the first like.
  const stackCards = useMemo(
    () => candidates.map((c) => ({ ...c, id: c.candidate_id })),
    [candidates],
  );
  const stackDepleted = votedCount >= candidates.length;

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Шаг 1 — типаж"
        description="Лайкайте образы, которые откликаются. Нужно минимум 3 лайка, чтобы перейти к подбору из вашего гардероба."
      />

      <SwipeStack
        cards={stackCards}
        onVote={({ card, action }) => onVote(card, action)}
        renderCard={({ card, depth, overlay, onVote: vote, disabled }) => (
          <QuizCard
            imageUrl={card.image_url}
            title={card.title ?? formatKibbeFamily(card.subtype)}
            subtitle={card.subtitle ?? null}
            depth={depth}
            overlay={overlay}
            disabled={disabled}
            onVote={vote}
          />
        )}
      />

      <SwipeStackProgress
        total={candidates.length}
        done={votedCount}
        likes={likeCount}
      />

      {error ? (
        <ErrorState
          title={
            error instanceof ApiError && error.status === 422
              ? "Нужно больше лайков"
              : "Не удалось собрать образы из гардероба"
          }
          error={error}
          onRetry={onAdvance}
        />
      ) : null}

      <div className="flex flex-wrap gap-3">
        <Button
          onClick={onAdvance}
          disabled={!canAdvance}
          loading={advancing}
          size="lg"
        >
          {stackDepleted ? "Показать как собрать" : "Готово, к подбору из гардероба"}
        </Button>
        {!canAdvance ? (
          <span className="self-center text-xs text-ink-muted">
            Ещё {Math.max(0, 3 - likeCount)} лайка до следующего шага
          </span>
        ) : null}
      </div>
    </div>
  );
}

function ColorFamilyStep({
  candidates,
  likeCount,
  votedCount,
  onVote,
  onAdvance,
  canAdvance,
  advancing,
  error,
}: {
  candidates: ColorFamilyCandidate[];
  likeCount: number;
  votedCount: number;
  onVote: (card: ColorFamilyCandidate, action: "like" | "dislike") => void;
  onAdvance: () => void;
  canAdvance: boolean;
  advancing: boolean;
  error: unknown;
}) {
  if (candidates.length === 0) {
    return (
      <EmptyState
        title="Нет карточек палитры"
        hint="Контент пока не готов — попробуйте позже."
      />
    );
  }
  // See IdentityStockStep — stable ref required so SwipeStack doesn't
  // reset its `remaining` queue after every parent re-render.
  const stackCards = useMemo(
    () => candidates.map((c) => ({ ...c, id: c.candidate_id })),
    [candidates],
  );
  return (
    <div className="space-y-6">
      <SectionHeader
        title="Шаг 3 — палитра"
        description="4 образа с цветом у лица. Отметьте, где лицо становится живее."
      />

      <SwipeStack
        cards={stackCards}
        onVote={({ card, action }) => onVote(card, action)}
        renderCard={({ card, depth, overlay, onVote: vote, disabled }) => (
          <ColorDraperyCard
            imageUrl={card.image_url}
            label={card.title ?? formatFamily(card.family)}
            hex={card.hex}
            depth={depth}
            overlay={overlay}
            disabled={disabled}
            onVote={vote}
          />
        )}
      />

      <SwipeStackProgress
        total={candidates.length}
        done={votedCount}
        likes={likeCount}
      />

      {error ? (
        <ErrorState
          title="Не удалось перейти к следующему шагу"
          error={error}
          onRetry={onAdvance}
        />
      ) : null}

      <Button
        onClick={onAdvance}
        disabled={!canAdvance}
        loading={advancing}
        size="lg"
      >
        Уточнить сезон
      </Button>
    </div>
  );
}

function ColorSeasonStep({
  candidates,
  votedCount,
  onVote,
  onAllVoted,
  completing,
  error,
}: {
  candidates: ColorSeasonCandidate[];
  votedCount: number;
  onVote: (card: ColorSeasonCandidate, action: "like" | "dislike") => void;
  onAllVoted: () => void;
  completing: boolean;
  error: unknown;
}) {
  if (candidates.length === 0) {
    return (
      <EmptyState
        title="Нет карточек сезона"
        hint="Похоже, квиз не смог определить семью. Начните заново."
      />
    );
  }
  // See IdentityStockStep — stable ref required so SwipeStack doesn't
  // reset its `remaining` queue after every parent re-render.
  const stackCards = useMemo(
    () => candidates.map((c) => ({ ...c, id: c.candidate_id })),
    [candidates],
  );
  return (
    <div className="space-y-6">
      <SectionHeader
        title="Шаг 4 — сезон"
        description="Тонкие различия внутри одной семьи. Лайкните ближайшее."
      />

      <SwipeStack
        cards={stackCards}
        onVote={({ card, action }) => onVote(card, action)}
        onFinished={() => onAllVoted()}
        renderCard={({ card, depth, overlay, onVote: vote, disabled }) => (
          <ColorDraperyCard
            imageUrl={card.image_url}
            label={card.title ?? formatSeason(card.season)}
            hex={card.hex}
            depth={depth}
            overlay={overlay}
            disabled={disabled}
            onVote={vote}
          />
        )}
      />

      <SwipeStackProgress
        total={candidates.length}
        done={votedCount}
        likes={votedCount}
      />

      {completing ? (
        <Card>
          <p className="text-sm text-ink-muted">Сохраняем результат…</p>
        </Card>
      ) : null}

      {error ? (
        <ErrorState title="Не удалось завершить квиз" error={error} />
      ) : null}
    </div>
  );
}

function ResultStep({
  algorithmicKibbe,
  algorithmicSeason,
  preferenceKibbe,
  preferenceSeason,
  currentSource,
  onPick,
  isApplying,
  error,
}: {
  algorithmicKibbe: string | null;
  algorithmicSeason: string | null;
  preferenceKibbe: string | null;
  preferenceSeason: string | null;
  currentSource: ProfileSource;
  onPick: (src: ProfileSource) => void;
  isApplying: boolean;
  error: unknown;
}) {
  return (
    <div className="space-y-6">
      <ResultReveal
        algorithmicKibbe={algorithmicKibbe}
        algorithmicSeason={algorithmicSeason}
        preferenceKibbe={preferenceKibbe}
        preferenceSeason={preferenceSeason}
        currentSource={currentSource}
        onPick={onPick}
        isApplying={isApplying}
      />

      {error ? (
        <ErrorState
          title="Не удалось переключить профиль"
          error={error}
          onRetry={() =>
            onPick(currentSource === "algorithmic" ? "preference" : "algorithmic")
          }
        />
      ) : null}

      <div className="flex flex-wrap gap-3">
        <Link href="/recommendations">
          <Button variant="secondary">Открыть рекомендации</Button>
        </Link>
        <Link href="/today">
          <Button variant="ghost">На сегодня</Button>
        </Link>
      </div>
    </div>
  );
}

// ---------- local helpers ----------

function formatFamily(key: string): string {
  const FAMILIES: Record<string, string> = {
    spring: "Весна",
    summer: "Лето",
    autumn: "Осень",
    winter: "Зима",
  };
  return FAMILIES[key.toLowerCase()] ?? key;
}
