import Link from "next/link";
import { Button } from "@/components/ui/Button";

/**
 * Public landing page.
 *
 * The page is static — no client-side state, no React Query — so it
 * renders at full quality on first paint even if JS is slow. The only
 * CTA is "Попробовать бесплатно", which takes the visitor straight to
 * ``/analyze`` (no waitlist, no email capture — see the closed-beta
 * plan: we prefer a low-friction direct entry over an email wall).
 *
 * Sections, in order:
 *   1. Hero — leads with the main user pain ("шкаф полный, нечего
 *      надеть") then softens into the product's emotional promise.
 *   2. «Как это работает» — three concrete steps, short and sequenced.
 *   3. «Что может смущать» — four common objections from
 *      ``.business/audience/objections.md``, each with a direct answer.
 *   4. Final CTA — repeats the ask for readers who scrolled.
 *
 * Keep one <h1> on the page — ``mobile-check.js`` asserts it.
 */

const STEPS = [
  {
    title: "Три фото — и мы вас читаем",
    body:
      "Анфас, профиль, портрет. За минуту — ваш цветотип, тип фигуры и стиль. Фото остаются в вашем аккаунте.",
  },
  {
    title: "Покажите гардероб — по одной вещи",
    body:
      "Добавляйте когда удобно, не обязательно сразу весь шкаф. Даже трёх вещей хватит для первого образа.",
  },
  {
    title: "Получайте готовые образы",
    body:
      "Каждое утро — три варианта: безопасный, сбалансированный, смелый. К каждому — объяснение, почему он работает.",
  },
];

const OBJECTIONS = [
  {
    worry: "Не хочу загружать свои фото",
    answer:
      "Фото остаются в вашем аккаунте и используются только для анализа. Лицо не обязательно — подойдёт фото с шеи вниз.",
  },
  {
    worry: "AI-стилист? Звучит странно",
    answer:
      "Мы не претендуем заменить живого стилиста. Зато к каждой рекомендации объясняем логику — вы видите почему, а не просто что.",
  },
  {
    worry: "Нет времени фотографировать весь шкаф",
    answer:
      "И не надо. Добавляйте по одной вещи. Чем больше — тем точнее образы, но уже с трёх-четырёх можно начать.",
  },
  {
    worry: "Ещё одна платная подписка",
    answer:
      "Подписки нет. Базовые функции бесплатны навсегда. Платите только если понадобятся дополнительные примерки или расширенный разбор.",
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

      {/* --- Hero ----------------------------------------------------- */}
      <main className="container-page pb-24 pt-16 sm:pt-24">
        <section className="max-w-2xl">
          <p className="mb-4 text-xs font-medium uppercase tracking-[0.18em] text-ink-muted">
            Шкаф полный — а надеть нечего?
          </p>
          <h1 className="font-display text-4xl leading-[1.05] tracking-tight sm:text-6xl">
            Одевайтесь так, как чувствуете.
          </h1>
          <p className="mt-5 max-w-xl text-base text-ink-muted sm:text-lg">
            AI Stylist читает вашу фигуру, палитру и гардероб — и собирает
            образы из того, что у вас уже есть. С объяснением, почему оно
            работает.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/analyze">
              <Button size="lg">Попробовать бесплатно</Button>
            </Link>
            <Link href="/today">
              <Button size="lg" variant="secondary">
                Посмотреть день
              </Button>
            </Link>
          </div>
          <p className="mt-4 text-xs text-ink-muted">
            Без регистрации и без карты. Первый результат — за минуту.
          </p>
        </section>

        {/* --- Как это работает --------------------------------------- */}
        <section className="mt-20 sm:mt-28">
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-ink-muted">
            Как это работает
          </p>
          <h2 className="mt-2 font-display text-3xl tracking-tight sm:text-4xl">
            Три шага до первого образа
          </h2>
          <div className="mt-8 grid gap-4 sm:grid-cols-3">
            {STEPS.map((s, i) => (
              <div
                key={s.title}
                className="rounded-2xl border border-canvas-border bg-canvas-card p-6"
              >
                <span className="text-xs font-medium uppercase tracking-[0.14em] text-ink-muted">
                  Шаг {String(i + 1).padStart(2, "0")}
                </span>
                <h3 className="mt-3 text-base font-semibold tracking-tight">
                  {s.title}
                </h3>
                <p className="mt-2 text-sm text-ink-muted">{s.body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* --- Что может смущать -------------------------------------- */}
        <section className="mt-20 sm:mt-28">
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-ink-muted">
            Что может смущать
          </p>
          <h2 className="mt-2 font-display text-3xl tracking-tight sm:text-4xl">
            Честно, без маркетингового тумана
          </h2>
          <div className="mt-8 grid gap-4 sm:grid-cols-2">
            {OBJECTIONS.map((o) => (
              <div
                key={o.worry}
                className="rounded-2xl border border-canvas-border bg-canvas-card p-6"
              >
                <p className="text-sm font-semibold tracking-tight text-ink">
                  «{o.worry}»
                </p>
                <p className="mt-2 text-sm text-ink-muted">{o.answer}</p>
              </div>
            ))}
          </div>
        </section>

        {/* --- Final CTA ---------------------------------------------- */}
        <section className="mt-20 sm:mt-28">
          <div className="rounded-3xl border border-canvas-border bg-canvas-card p-8 sm:p-12">
            <div className="mx-auto max-w-xl text-center">
              <h2 className="font-display text-3xl tracking-tight sm:text-4xl">
                Посмотрите, что у вас уже есть
              </h2>
              <p className="mt-3 text-sm text-ink-muted sm:text-base">
                Один разбор занимает столько же времени, сколько вы стоите
                перед шкафом по утрам.
              </p>
              <div className="mt-6 flex justify-center">
                <Link href="/analyze">
                  <Button size="lg">Начать бесплатно</Button>
                </Link>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-canvas-border">
        <div className="container-page flex flex-col items-center justify-between gap-2 py-6 text-xs text-ink-muted sm:flex-row">
          <span>© {new Date().getFullYear()} AI Stylist</span>
          <span>Закрытая бета. Пишите фидбек прямо из приложения.</span>
        </div>
      </footer>
    </div>
  );
}
