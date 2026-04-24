import { z } from "zod";
import { apiRequest } from "./client";

// -------------------------------------------------------- schemas

export const PersonaSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  is_primary: z.boolean(),
  created_at: z.string(),
});
export type Persona = z.infer<typeof PersonaSchema>;

const PersonaListSchema = z.object({
  personas: z.array(PersonaSchema),
});

// -------------------------------------------------------- endpoints

export async function listPersonas(): Promise<Persona[]> {
  const data = await apiRequest("/personas");
  return PersonaListSchema.parse(data).personas;
}

export async function createPersona(name: string): Promise<Persona> {
  const data = await apiRequest("/personas", {
    method: "POST",
    json: { name },
  });
  return PersonaSchema.parse(data);
}

export async function renamePersona(
  id: string,
  name: string
): Promise<Persona> {
  const data = await apiRequest(`/personas/${id}`, {
    method: "PATCH",
    json: { name },
  });
  return PersonaSchema.parse(data);
}

export async function deletePersona(id: string): Promise<void> {
  await apiRequest(`/personas/${id}`, { method: "DELETE" });
}
