import Link from "next/link";
import { Button } from "@/components/ui/Button";

const FEATURES = [
  {
    title: "Личный анализ",
    body: "Три фото — и понятно, как читать вашу фигуру, палитру и стиль.",
  },
  {
    title: "Гардероб, который думает",
    body: "Загрузите то, что у вас есть. Превращаем это в образы, которые реально носят.",
  },
  {
    title: "День, собранный за вас",
    body: "Каждое утро — три варианта: безопасный, сбалансированный и смелый.",
  },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-canvas">
      <header className="container-page flex h-16 items-center justify-between">
        <span className="font-display text-xl tracking-tight">AI Stylist</span>
        <Link
          href="/sign-in"
          className="text-sm font-medium text-ink-muted transition-colors hover:text-ink"
        >
          Войти
        </Link>
      </header>

      <main className="container-page pb-24 pt-16 sm:pt-24">
        <section className="max-w-2xl">
          <p className="mb-4 text-xs font-medium uppercase tracking-[0.18em] text-ink-muted">
            Ваш персональный стилист
          </p>
          <h1 className="font-display text-4xl leading-[1.05] tracking-tight sm:text-6xl">
            Одевайтесь так, как чувствуете.
          </h1>
          <p className="mt-5 max-w-xl text-base text-ink-muted sm:text-lg">
            AI Stylist считывает вашу фигуру, цвета и гардероб — и тихо собирает
            образы, в которых вы похожи на себя в лучший день.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/analyze">
              <Button size="lg">Начать с анализа</Button>
            </Link>
            <Link href="/today">
              <Button size="lg" variant="secondary">
                Посмотреть день
              </Button>
            </Link>
          </div>
        </section>

        <section className="mt-20 grid gap-4 sm:mt-24 sm:grid-cols-3">
          {FEATURES.map((f, i) => (
            <div
              key={f.title}
              className="rounded-2xl border border-canvas-border bg-canvas-card p-6"
            >
              <span className="text-xs font-medium uppercase tracking-[0.14em] text-ink-muted">
                {String(i + 1).padStart(2, "0")}
              </span>
              <h3 className="mt-3 text-base font-semibold tracking-tight">
                {f.title}
              </h3>
              <p className="mt-2 text-sm text-ink-muted">{f.body}</p>
            </div>
          ))}
        </section>
      </main>
    </div>
  );
}
