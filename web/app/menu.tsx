"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

// "⋯": a card's less used actions. Opens above the button, or below when there's no room above
// (the first card, under the sticky header). Closes on a click outside or Escape.
export function Menu({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [below, setBelow] = useState(false);
  const [shift, setShift] = useState<number | null>(null); // px from the button's left edge, kept on screen
  const box = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!open || !box.current || !panel.current) return;
    const button = box.current.getBoundingClientRect();
    const header = document.querySelector("header")?.getBoundingClientRect().bottom ?? 0;
    const room = button.top - header; // space between the sticky header and the button
    setBelow(room < panel.current.offsetHeight + 12);
    // line its right edge up with the button's, then slide it back inside the screen (8 px margin)
    const width = panel.current.offsetWidth;
    const left = Math.min(Math.max(8, button.right - width), window.innerWidth - 8 - width);
    setShift(left - button.left);
  }, [open]);

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
        <div
          ref={panel}
          data-placement={below ? "below" : "above"}
          style={shift === null ? { right: 0 } : { left: shift }}
          className={`absolute z-20 flex w-max max-w-[min(18rem,calc(100vw-1rem))] flex-wrap gap-2 rounded-xl border border-zinc-200 bg-white p-2 shadow-lg dark:border-zinc-700 dark:bg-zinc-900 ${
            below ? "top-full mt-2" : "bottom-full mb-2"
          }`}
        >
          {children}
        </div>
      )}
    </div>
  );
}
