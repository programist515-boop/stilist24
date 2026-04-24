import type { ReactNode } from "react";
import { NavBar } from "./NavBar";
import { MobileNav } from "./MobileNav";
import { FeedbackButton } from "@/components/feedback/FeedbackButton";
import { PageViewTracker } from "@/components/feedback/PageViewTracker";
import { PersonaProvider } from "@/providers/PersonaProvider";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <PersonaProvider>
      <div className="min-h-screen bg-canvas pb-28 lg:pb-0">
        <NavBar />
        <main className="container-page space-y-8 py-6 sm:py-10">
          {children}
        </main>
        <MobileNav />
        <FeedbackButton />
        <PageViewTracker />
      </div>
    </PersonaProvider>
  );
}
