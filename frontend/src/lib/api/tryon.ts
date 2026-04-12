import { apiRequest } from "./client";
import { TryOnJobSchema, type TryOnJob } from "@/lib/schemas";

export async function generateTryOn(input: {
  item_id: string;
  user_photo_id: string;
}): Promise<TryOnJob> {
  const data = await apiRequest("/tryon/generate", {
    method: "POST",
    json: input,
  });
  return TryOnJobSchema.parse(data);
}

export async function getTryOnJob(jobId: string): Promise<TryOnJob> {
  const data = await apiRequest(`/tryon/${jobId}`);
  return TryOnJobSchema.parse(data);
}
