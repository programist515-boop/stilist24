import { apiRequest } from "./client";
import { TodayResponseSchema, type TodayResponse } from "@/lib/schemas";

export async function getToday(input?: {
  weather?: string;
  occasion?: string;
}): Promise<TodayResponse> {
  const data = await apiRequest("/today", {
    query: { weather: input?.weather, occasion: input?.occasion },
  });
  return TodayResponseSchema.parse(data);
}
