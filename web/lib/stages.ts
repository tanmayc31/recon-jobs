// Application stages (tables `applications`, `application_events`, recon/store.py): shared by the
// server (lib/db.ts) and the Applied cards.

export const STAGES = ["applied", "assessment", "interview", "offer", "rejected", "ghosted", "withdrawn"] as const;
export type Stage = (typeof STAGES)[number];
export const STAGE_LABELS: Record<Stage, string> = {
  applied: "Applied",
  assessment: "Assessment",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
  ghosted: "Ghosted",
  withdrawn: "Withdrawn",
};

// past Applied: the company answered (a rejection is an answer; ghosted and withdrawn aren't)
export const RESPONDED: Stage[] = ["assessment", "interview", "offer", "rejected"];
export const GHOST_DAYS = 21;

export const DETAILS = ["notes", "referral", "resume", "contact", "link", "deadline", "follow_up"] as const;
export type Detail = (typeof DETAILS)[number];

export type Application = {
  job_id: string;
  stage: Stage;
  applied_at: string | null; // null: applied before Recon tracked dates
  stage_at: string | null;
  prep: string | null;
  prep_state: "queued" | "done" | "failed" | null;
  events: { stage: Stage; at: string }[];
} & Record<Detail, string | null>;
