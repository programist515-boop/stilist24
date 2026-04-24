"use client";

import { useEffect, useRef, useState } from "react";
import { usePersona } from "@/providers/PersonaProvider";
import { cn } from "@/lib/cn";

/** Dropdown persona switcher for the nav bar.
 *
 * Shows the currently active persona, opens a menu with all personas
 * owned by the account, and exposes "New persona" + rename/delete on
 * secondary ones. Logout lives alongside so the whole "who am I" block
 * is one control.
 */
export function PersonaSwitcher() {
  const {
    personas,
    activePersona,
    switchPersona,
    addPersona,
    rename,
    remove,
    isLoading,
  } = usePersona();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement | null>(null);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setCreating(false);
        setRenamingId(null);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    try {
      const created = await addPersona(name);
      switchPersona(created.id);
      setNewName("");
      setCreating(false);
      setOpen(false);
      setError(null);
    } catch (exc) {
      setError((exc as Error).message);
    }
  };

  const handleRename = async (id: string) => {
    const name = renameDraft.trim();
    if (!name) return;
    try {
      await rename(id, name);
      setRenamingId(null);
      setRenameDraft("");
      setError(null);
    } catch (exc) {
      setError((exc as Error).message);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Удалить этот профиль? Данные останутся только в аккаунте владельца.")) {
      return;
    }
    try {
      await remove(id);
      setError(null);
    } catch (exc) {
      setError((exc as Error).message);
    }
  };

  const label = activePersona?.name ?? (isLoading ? "…" : "Профиль");

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex items-center gap-1 rounded-full border border-canvas-border bg-canvas px-3 py-1.5 text-sm font-medium text-ink",
          "hover:bg-accent-soft"
        )}
      >
        <span className="max-w-[120px] truncate">{label}</span>
        <svg
          className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")}
          viewBox="0 0 20 20"
          fill="currentColor"
          aria-hidden
        >
          <path
            fillRule="evenodd"
            d="M5.23 7.21a.75.75 0 011.06.02L10 11.06l3.71-3.83a.75.75 0 111.08 1.04l-4.25 4.39a.75.75 0 01-1.08 0L5.21 8.27a.75.75 0 01.02-1.06z"
            clipRule="evenodd"
          />
        </svg>
      </button>

      {open && (
        <div className="absolute right-0 top-full z-20 mt-2 w-72 rounded-2xl border border-canvas-border bg-canvas p-2 shadow-xl">
          <div className="px-3 py-1 text-xs font-semibold uppercase text-ink-muted">
            Профили в этом аккаунте
          </div>
          <ul className="mt-1 flex flex-col">
            {personas.map((p) => {
              const isActive = p.id === activePersona?.id;
              if (renamingId === p.id) {
                return (
                  <li key={p.id} className="flex items-center gap-2 px-2 py-1">
                    <input
                      value={renameDraft}
                      onChange={(e) => setRenameDraft(e.target.value)}
                      autoFocus
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleRename(p.id);
                        if (e.key === "Escape") setRenamingId(null);
                      }}
                      className="flex-1 rounded-md border border-canvas-border px-2 py-1 text-sm"
                    />
                    <button
                      onClick={() => handleRename(p.id)}
                      className="text-xs text-accent"
                    >
                      OK
                    </button>
                  </li>
                );
              }
              return (
                <li key={p.id} className="group flex items-center justify-between gap-1 rounded-lg px-2 py-1 hover:bg-accent-soft">
                  <button
                    type="button"
                    onClick={() => {
                      switchPersona(p.id);
                      setOpen(false);
                    }}
                    className="flex-1 truncate text-left text-sm"
                  >
                    <span className={cn(isActive && "font-semibold")}>{p.name}</span>
                    {p.is_primary && (
                      <span className="ml-1 text-xs text-ink-muted">(основной)</span>
                    )}
                    {isActive && (
                      <span className="ml-1 text-xs text-accent">● активен</span>
                    )}
                  </button>
                  <div className="flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                    <button
                      type="button"
                      onClick={() => {
                        setRenamingId(p.id);
                        setRenameDraft(p.name);
                      }}
                      className="rounded px-1 py-0.5 text-xs text-ink-muted hover:bg-canvas"
                      title="Переименовать"
                    >
                      ✎
                    </button>
                    {!p.is_primary && (
                      <button
                        type="button"
                        onClick={() => handleDelete(p.id)}
                        className="rounded px-1 py-0.5 text-xs text-red-600 hover:bg-canvas"
                        title="Удалить"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>

          <div className="mt-2 border-t border-canvas-border pt-2">
            {creating ? (
              <div className="flex items-center gap-2 px-2 py-1">
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  autoFocus
                  placeholder="Имя профиля (напр. «Мама»)"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleCreate();
                    if (e.key === "Escape") setCreating(false);
                  }}
                  className="flex-1 rounded-md border border-canvas-border px-2 py-1 text-sm"
                />
                <button
                  onClick={handleCreate}
                  className="rounded-md bg-ink px-2 py-1 text-xs text-canvas"
                >
                  Создать
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setCreating(true)}
                className="w-full rounded-lg px-2 py-2 text-left text-sm font-medium text-accent hover:bg-accent-soft"
              >
                + Новый профиль
              </button>
            )}
          </div>

          {error && (
            <div className="mt-2 rounded-md bg-red-50 px-2 py-1 text-xs text-red-700">
              {error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
