import { z } from "zod";
import { apiRequest } from "./client";

// -------------------------------------------------------- schemas

export const TokenOutSchema = z.object({
  access_token: z.string(),
  token_type: z.string().default("bearer"),
  user_id: z.string().uuid(),
});
export type TokenOut = z.infer<typeof TokenOutSchema>;

export const MeOutSchema = z.object({
  user_id: z.string().uuid(),
  email: z.string().nullable(),
  auth_provider: z.string(),
});
export type MeOut = z.infer<typeof MeOutSchema>;

// -------------------------------------------------------- endpoints

export async function signup(
  email: string,
  password: string
): Promise<TokenOut> {
  const data = await apiRequest("/auth/signup", {
    method: "POST",
    json: { email, password },
  });
  return TokenOutSchema.parse(data);
}

export async function login(
  email: string,
  password: string
): Promise<TokenOut> {
  const data = await apiRequest("/auth/login", {
    method: "POST",
    json: { email, password },
  });
  return TokenOutSchema.parse(data);
}

export async function fetchMe(): Promise<MeOut> {
  const data = await apiRequest("/auth/me");
  return MeOutSchema.parse(data);
}
