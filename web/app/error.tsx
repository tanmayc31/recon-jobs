"use client";

// Anything the page itself didn't catch (lib/db.ts times out slow queries): a message and a retry,
// not a blank page or a hang.
export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="mx-auto mt-24 w-full max-w-md px-4 text-center">
      <h1 className="text-lg font-semibold">Recon couldn&apos;t load this page</h1>
      <p className="mt-2 text-sm text-zinc-500">
        {error.message.includes("longer than") ? "The database didn't answer in time." : "Something went wrong."}
        {error.digest && <span className="block text-xs">Error {error.digest}</span>}
      </p>
      <button
        onClick={reset}
        className="mt-5 rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
      >
        Try again
      </button>
    </div>
  );
}
