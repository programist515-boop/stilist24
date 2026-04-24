import { apiRequest } from "./client";
import {
  ReferenceLooksResponseSchema,
  type ReferenceLooksResponse,
} from "@/lib/schemas/referenceLooks";

/**
 * API-клиент для /reference-looks.
 *
 * Один вызов:
 *  - GET /reference-looks — референсные луки активного подтипа
 *    пользователя, собранные из его гардероба; missing_slots —
 *    потенциальные кандидаты для докупки.
 */
export async function getReferenceLooks(): Promise<ReferenceLooksResponse> {
  const data = await apiRequest(`/reference-looks`);
  return ReferenceLooksResponseSchema.parse(data);
}
