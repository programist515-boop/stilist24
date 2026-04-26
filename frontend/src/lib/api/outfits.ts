import { apiRequest } from "./client";
import {
  OutfitGenerateResponseSchema,
  type OutfitGenerateResponse,
} from "@/lib/schemas";

export async function generateOutfits(input: {
  occasion?: string;
  season?: string;
  style?: string;
}): Promise<OutfitGenerateResponse> {
  const data = await apiRequest("/outfits/generate", {
    method: "POST",
    json: input,
  });
  return OutfitGenerateResponseSchema.parse(data);
}
