"use client";

import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { cn } from "@/lib/cn";

interface FileDropzoneProps {
  label: string;
  accept?: string;
  file: File | null;
  /**
   * Preloaded image URL shown when no fresh `file` has been picked.
   * Used to render persisted server-side photos so users don't have
   * to re-upload them every time they re-open the page.
   */
  preloadedUrl?: string | null;
  onChange: (file: File | null) => void;
  className?: string;
}

export function FileDropzone({
  label,
  accept = "image/*",
  file,
  preloadedUrl = null,
  onChange,
  className,
}: FileDropzoneProps) {
  const [hover, setHover] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Build object URL for fresh File picks, and revoke it on cleanup
  // so we don't leak blobs when the user replaces the photo.
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!file) {
      setObjectUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setObjectUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const previewUrl = objectUrl ?? preloadedUrl;

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setHover(false);
      const dropped = e.dataTransfer.files?.[0];
      if (dropped) onChange(dropped);
    },
    [onChange]
  );

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setHover(true);
      }}
      onDragLeave={() => setHover(false)}
      onDrop={handleDrop}
      className={cn(
        "group relative flex aspect-[3/4] cursor-pointer flex-col items-center justify-center overflow-hidden rounded-2xl border border-dashed border-canvas-border bg-canvas-card text-center transition-colors",
        hover && "border-ink bg-accent-soft",
        className
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => onChange(e.target.files?.[0] ?? null)}
      />
      {previewUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={previewUrl}
          alt={label}
          className="absolute inset-0 h-full w-full object-cover"
        />
      ) : (
        <div className="px-4">
          <p className="text-sm font-medium text-ink">{label}</p>
          <p className="mt-1 text-xs text-ink-muted">
            Нажмите или перетащите изображение
          </p>
        </div>
      )}
    </div>
  );
}
