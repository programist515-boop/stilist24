import { FileDropzone } from "@/components/ui/FileDropzone";

interface PhotoSlotProps {
  index: number;
  label: string;
  hint: string;
  file: File | null;
  onChange: (file: File | null) => void;
}

export function PhotoSlot({
  index,
  label,
  hint,
  file,
  onChange,
}: PhotoSlotProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span
          className={
            "flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold transition-colors " +
            (file
              ? "bg-ink text-canvas"
              : "bg-accent-soft text-ink-muted")
          }
        >
          {index}
        </span>
        <div className="flex-1">
          <p className="text-sm font-semibold text-ink">{label}</p>
          <p className="text-xs text-ink-muted">{hint}</p>
        </div>
      </div>
      <FileDropzone label={label} file={file} onChange={onChange} />
    </div>
  );
}
