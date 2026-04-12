import { apiRequest } from "./client";
import {
  RecommendationGuideSchema,
  type RecommendationGuide,
} from "@/lib/schemas";

/**
 * Fetch the curated stylist guide for the acting user.
 *
 * Backed by `GET /recommendations/style-guide` in
 * `app/api/routes/recommendations.py`. The response is a deterministic
 * projection of the user's Kibbe family + color profile + style vector
 * into a pre-written content bundle, so it's safe to cache client-side
 * with a long `staleTime`.
 *
 * Empty-state handling lives in the caller: when the user hasn't
 * finished the analysis, the backend returns an empty `sections` list
 * and a single message in `notes`, and the page renders an
 * `EmptyState` pointing to `/analyze` instead of an error.
 */
export async function getRecommendationGuide(): Promise<RecommendationGuide> {
  const data = await apiRequest("/recommendations/style-guide");
  return RecommendationGuideSchema.parse(data);
}
