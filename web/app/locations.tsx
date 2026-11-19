"use client";

import { useState } from "react";

// A card's locations: the first SHOWN, then "+N more" to see the rest (merged copies get long)
const SHOWN = 2;

export function Locations({ text }: { text: string }) {
  const [all, setAll] = useState(false);
  const places = text.split("; ").filter(Boolean);
  const extra = places.length - SHOWN;
  return (
    <p className="mt-1 text-sm text-zinc-500">
      {all || extra <= 0 ? places.join("; ") : places.slice(0, SHOWN).join("; ")}
      {extra > 0 && (
        <button
          type="button"
          onClick={() => setAll((a) => !a)}
          aria-expanded={all}
          className="ml-1.5 font-medium text-zinc-700 underline decoration-dotted underline-offset-2 hover:text-zinc-900 dark:text-zinc-300 dark:hover:text-zinc-100"
        >
          {all ? "show less" : `+${extra} more`}
        </button>
      )}
    </p>
  );
}
