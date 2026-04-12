import { apiRequest } from "./client";
import { InsightsResponseSchema, type InsightsResponse } from "@/lib/schemas";

export async function getWeeklyInsights(): Promise<InsightsResponse> {
  const data = await apiRequest("/insights/weekly");
  return InsightsResponseSchema.parse(data);
}
