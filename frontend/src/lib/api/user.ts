import { z } from "zod";
import { apiRequest } from "./client";
import {
  AnalysisPhotoSchema,
  UserAnalysisSchema,
  type AnalysisPhoto,
  type UserAnalysis,
} from "@/lib/schemas";

export async function analyzeUser(input: {
  front: File;
  side: File;
  portrait: File;
}): Promise<UserAnalysis> {
  const form = new FormData();
  form.append("front_photo", input.front);
  form.append("side_photo", input.side);
  form.append("portrait_photo", input.portrait);

  const data = await apiRequest("/user/analyze", {
    method: "POST",
    form,
  });
  return UserAnalysisSchema.parse(data);
}

/**
 * Return the caller's stored reference photos from the backend.
 *
 * Screens that need reference photos (Try-On, Today) previously read
 * a snapshot of the last `/user/analyze` response from localStorage.
 * That cache is poisoned the moment the backend's public URL base
 * changes (e.g. after fixing `S3_PUBLIC_BASE_URL`), so we always hit
 * the live `GET /user/photos` endpoint instead — it returns fresh
 * rows from `user_photos` with whatever `image_url` the storage layer
 * currently projects.
 */
export async function listUserPhotos(): Promise<AnalysisPhoto[]> {
  const data = await apiRequest("/user/photos");
  return z.array(AnalysisPhotoSchema).parse(data);
}
