"use client";

import { QuizCard } from "./QuizCard";
import type { VoteAction } from "@/lib/schemas/preferenceQuiz";

interface ColorDraperyCardProps {
  imageUrl: string | null | undefined;
  label: string;
  hex: string;
  subtitle?: string | null;
  disabled?: boolean;
  onVote: (action: VoteAction) => void;
  overlay?: VoteAction | null;
  depth?: number;
}

/**
 * Specialisation of `QuizCard` for the color quiz. Adds a colour swatch
 * badge so the user links the face composite to the actual palette hex.
 */
export function ColorDraperyCard({
  imageUrl,
  label,
  hex,
  subtitle,
  disabled,
  onVote,
  overlay,
  depth,
}: ColorDraperyCardProps) {
  return (
    <QuizCard
      imageUrl={imageUrl}
      title={label}
      subtitle={subtitle ?? hex.toUpperCase()}
      badge={{ label: hex.toUpperCase(), hex }}
      disabled={disabled}
      onVote={onVote}
      overlay={overlay}
      depth={depth}
    />
  );
}
