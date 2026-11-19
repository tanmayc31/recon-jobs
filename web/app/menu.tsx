"use client";

import { useEffect, useRef, useState } from "react";

// "⋯": the less used actions on an Applied card. Closes on a click outside or Escape.
export function Menu({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    const escape = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label="More actions"
        title="More actions"
        className="rounded-lg border border-zinc-300 px-3 py-2 text-sm font-medium leading-none hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
      >
        ⋯
      </button>
      {open && (
        <div className="absolute bottom-full right-0 z-20 mb-2 flex w-max max-w-[18rem] flex-wrap gap-2 rounded-xl border border-zinc-200 bg-white p-2 shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
          {children}
        </div>
      )}
    </div>
  );
}
