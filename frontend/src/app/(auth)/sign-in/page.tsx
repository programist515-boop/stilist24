"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card, CardSubtitle, CardTitle } from "@/components/ui/Card";
import { login, signup } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";
import {
  clearSession,
  getAccessToken,
  setAccessToken,
} from "@/lib/session";

type Mode = "signup" | "login";

export default function SignInPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("signup");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasToken, setHasToken] = useState(false);

  useEffect(() => {
    setHasToken(getAccessToken() !== null);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const result =
        mode === "signup"
          ? await signup(email.trim(), password)
          : await login(email.trim(), password);
      setAccessToken(result.access_token);
      router.push("/analyze");
    } catch (exc) {
      if (exc instanceof ApiError) {
        setError(exc.message);
      } else {
        setError((exc as Error).message ?? "Не удалось войти");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleLogout = () => {
    clearSession();
    setHasToken(false);
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
      <div className="w-full max-w-md">
        <h1 className="sr-only">Вход в AI Stylist</h1>
        <div className="mb-8 text-center">
          <Link href="/" className="font-display text-2xl tracking-tight">
            AI Stylist
          </Link>
          <p className="mt-2 text-sm text-ink-muted">
            Войдите, чтобы фото, гардероб и анализ привязались к вашему аккаунту
            и были доступны на любом устройстве.
          </p>
        </div>

        {hasToken ? (
          <Card>
            <CardTitle>Вы уже внутри</CardTitle>
            <CardSubtitle className="mt-1">
              У вас активная сессия. Продолжайте работу или выйдите, чтобы
              войти под другим email.
            </CardSubtitle>
            <div className="mt-6 flex flex-col gap-2">
              <Button onClick={() => router.push("/today")}>
                Перейти в «Сегодня»
              </Button>
              <Button variant="secondary" onClick={() => router.push("/analyze")}>
                Анализ внешности
              </Button>
              <Button variant="secondary" onClick={handleLogout}>
                Выйти
              </Button>
            </div>
          </Card>
        ) : (
          <Card>
            <div className="mb-4 flex gap-2">
              <button
                type="button"
                onClick={() => {
                  setMode("signup");
                  setError(null);
                }}
                className={`flex-1 rounded-full px-3 py-1.5 text-sm font-medium ${
                  mode === "signup"
                    ? "bg-ink text-canvas"
                    : "text-ink-muted hover:bg-accent-soft"
                }`}
              >
                Регистрация
              </button>
              <button
                type="button"
                onClick={() => {
                  setMode("login");
                  setError(null);
                }}
                className={`flex-1 rounded-full px-3 py-1.5 text-sm font-medium ${
                  mode === "login"
                    ? "bg-ink text-canvas"
                    : "text-ink-muted hover:bg-accent-soft"
                }`}
              >
                Вход
              </button>
            </div>

            <CardTitle>
              {mode === "signup" ? "Создать аккаунт" : "Войти в аккаунт"}
            </CardTitle>
            <CardSubtitle className="mt-1">
              {mode === "signup"
                ? "Email и пароль — данные останутся с вашим аккаунтом."
                : "Введите email и пароль, с которыми регистрировались."}
            </CardSubtitle>

            <form className="mt-5 flex flex-col gap-3" onSubmit={handleSubmit}>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium">Email</span>
                <input
                  type="email"
                  required
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="rounded-xl border border-canvas-border bg-canvas px-3 py-2 focus:border-accent focus:outline-none"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium">Пароль</span>
                <input
                  type="password"
                  required
                  minLength={mode === "signup" ? 8 : 1}
                  maxLength={64}
                  autoComplete={
                    mode === "signup" ? "new-password" : "current-password"
                  }
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="rounded-xl border border-canvas-border bg-canvas px-3 py-2 focus:border-accent focus:outline-none"
                />
                {mode === "signup" && (
                  <span className="text-xs text-ink-muted">
                    Минимум 8 символов.
                  </span>
                )}
              </label>

              {error && (
                <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
                  {error}
                </div>
              )}

              <Button type="submit" disabled={submitting}>
                {submitting
                  ? "Подождите…"
                  : mode === "signup"
                    ? "Создать аккаунт"
                    : "Войти"}
              </Button>

              <p className="text-center text-xs text-ink-muted">
                Продолжая, вы принимаете условия использования сервиса.
              </p>
            </form>
          </Card>
        )}
      </div>
    </div>
  );
}
