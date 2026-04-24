import { z } from "zod";
import { apiRequest } from "./client";

export const CelebritySchema = z.object({
  name: z.string(),
  era: z.string().nullable().optional(),
});
export type Celebrity = z.infer<typeof CelebritySchema>;

export const IdentityDNASchema = z.object({
  subtype: z.string().nullable(),
  display_name_ru: z.string().nullable(),
  display_name_en: z.string().nullable(),
  family: z.string().nullable(),
  associations: z.array(z.string()),
  motto: z.string(),
  philosophy: z.string(),
  key_principles: z.array(z.string()),
  celebrity_examples: z.array(CelebritySchema),
});
export type IdentityDNA = z.infer<typeof IdentityDNASchema>;

export async function fetchIdentityDNA(): Promise<IdentityDNA> {
  const data = await apiRequest("/identity-dna");
  return IdentityDNASchema.parse(data);
}
