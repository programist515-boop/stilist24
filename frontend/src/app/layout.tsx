import type { Metadata } from "next";
import "./globals.css";
import { QueryProvider } from "@/providers/QueryProvider";

export const metadata: Metadata = {
  title: "AI Stylist",
  description:
    "Ваш персональный стилист — анализ, гардероб, образы и подборки на каждый день.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ru">
      <body className="min-h-screen bg-canvas text-ink">
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
