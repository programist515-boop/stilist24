"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createPersona,
  deletePersona,
  listPersonas,
  renamePersona,
  type Persona,
} from "@/lib/api/personas";
import {
  getActivePersonaId,
  setActivePersonaId as writeActivePersonaId,
  clearActivePersonaId,
} from "@/lib/session";

type PersonaContextValue = {
  personas: Persona[];
  activePersona: Persona | null;
  activePersonaId: string | null;
  isLoading: boolean;
  error: Error | null;
  switchPersona: (id: string) => void;
  addPersona: (name: string) => Promise<Persona>;
  rename: (id: string, name: string) => Promise<Persona>;
  remove: (id: string) => Promise<void>;
  refresh: () => Promise<void>;
};

const PersonaContext = createContext<PersonaContextValue | null>(null);

export function PersonaProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [activeId, setActiveId] = useState<string | null>(null);

  // Hydrate the active persona id from localStorage once on the client.
  useEffect(() => {
    setActiveId(getActivePersonaId());
  }, []);

  const {
    data: personas = [],
    isLoading,
    error,
    refetch,
  } = useQuery<Persona[], Error>({
    queryKey: ["personas"],
    queryFn: listPersonas,
    staleTime: 60_000,
  });

  // If there is no active id, default to the primary persona as soon as
  // the list loads. We intentionally do NOT write to localStorage here —
  // letting a missing value mean "primary on the server" keeps the
  // dependency on the backend's own fallback (see ``ensure_primary``).
  const activePersona = useMemo<Persona | null>(() => {
    if (!personas.length) return null;
    if (activeId) {
      const match = personas.find((p) => p.id === activeId);
      if (match) return match;
    }
    return personas.find((p) => p.is_primary) ?? personas[0] ?? null;
  }, [personas, activeId]);

  // Switching personas flushes React Query caches so every screen
  // re-fetches against the new scope. Without this, the gardener's
  // ``/wardrobe`` cache would keep showing items from the previous
  // persona.
  const switchPersona = useCallback(
    (id: string) => {
      writeActivePersonaId(id);
      setActiveId(id);
      queryClient.removeQueries({
        predicate: (query) => {
          const key = query.queryKey[0];
          return typeof key === "string" && key !== "personas";
        },
      });
    },
    [queryClient]
  );

  const addPersona = useCallback(
    async (name: string) => {
      const created = await createPersona(name);
      await queryClient.invalidateQueries({ queryKey: ["personas"] });
      return created;
    },
    [queryClient]
  );

  const rename = useCallback(
    async (id: string, name: string) => {
      const updated = await renamePersona(id, name);
      await queryClient.invalidateQueries({ queryKey: ["personas"] });
      return updated;
    },
    [queryClient]
  );

  const remove = useCallback(
    async (id: string) => {
      await deletePersona(id);
      // If we just deleted the active one, drop the stored selection so
      // the next render falls back to primary.
      if (activeId === id) {
        clearActivePersonaId();
        setActiveId(null);
      }
      await queryClient.invalidateQueries({ queryKey: ["personas"] });
    },
    [queryClient, activeId]
  );

  const refresh = useCallback(async () => {
    await refetch();
  }, [refetch]);

  const value: PersonaContextValue = {
    personas,
    activePersona,
    activePersonaId: activePersona?.id ?? null,
    isLoading,
    error: (error as Error) ?? null,
    switchPersona,
    addPersona,
    rename,
    remove,
    refresh,
  };

  return (
    <PersonaContext.Provider value={value}>{children}</PersonaContext.Provider>
  );
}

export function usePersona(): PersonaContextValue {
  const ctx = useContext(PersonaContext);
  if (!ctx) {
    throw new Error(
      "usePersona must be used within <PersonaProvider> (AppShell wraps it)"
    );
  }
  return ctx;
}
