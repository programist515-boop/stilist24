"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card, CardSubtitle, CardTitle } from "@/components/ui/Card";
import { getUserId } from "@/lib/user-id";

export default function SignInPage() {
  const router = useRouter();
  const [userId, setUserIdState] = useState<string | null>(null);

  useEffect(() => {
    setUserIdState(getUserId());
  }, []);

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <Link href="/" className="font-display text-2xl tracking-tight">
            AI Stylist
          </Link>
          <p className="mt-2 text-sm text-ink-muted">
            Авторизация пока временная. Мы создаём стабильный идентификатор
            браузера и используем его как ваш аккаунт до полноценного входа.
          </p>
        </div>
        <Card>
          <CardTitle>Вы уже внутри</CardTitle>
          <CardSubtitle className="mt-1">
            Локальная сессия определяется этим идентификатором:
          </CardSubtitle>
          <code className="mt-4 block break-all rounded-xl bg-accent-soft px-4 py-3 text-xs">
            {userId ?? "загрузка…"}
          </code>
          <div className="mt-6 flex flex-col gap-2">
            <Button onClick={() => router.push("/analyze")}>
              Начать с анализа
            </Button>
            <Button variant="secondary" onClick={() => router.push("/today")}>
              Перейти в «Сегодня»
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}
