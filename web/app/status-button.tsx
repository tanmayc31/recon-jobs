"use client";

import { useFormStatus } from "react-dom";

export function StatusButton({
  children,
  className,
  label,
  pressed,
}: {
  children: React.ReactNode;
  className: string;
  label?: string;
  pressed?: boolean;
}) {
  const { pending } = useFormStatus();
  return (
    <button disabled={pending} aria-label={label} title={label} aria-pressed={pressed} className={`${className} disabled:opacity-50`}>
      {pending ? "…" : children}
    </button>
  );
}
