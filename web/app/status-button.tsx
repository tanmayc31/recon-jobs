"use client";

import { useFormStatus } from "react-dom";

export function StatusButton({ children, className }: { children: React.ReactNode; className: string }) {
  const { pending } = useFormStatus();
  return (
    <button disabled={pending} className={`${className} disabled:opacity-50`}>
      {pending ? "…" : children}
    </button>
  );
}
