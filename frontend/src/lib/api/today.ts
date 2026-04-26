import { apiRequest } from "./client";
import { TodayResponseSchema, type TodayResponse } from "@/lib/schemas";

export async function getToday(input?: {
  weather?: string;
  occasion?: string;
  style?: string;
}): Promise<TodayResponse> {
  const data = await apiRequest("/today", {
    query: {
      weather: input?.weather,
      occasion: input?.occasion,
      style: input?.style,
    },
  });
  return TodayResponseSchema.parse(data);
}
