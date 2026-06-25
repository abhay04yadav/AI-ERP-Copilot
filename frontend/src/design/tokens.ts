// Color/shape tokens lifted directly from the approved design
// (`Risk Copilot.dc.html`'s SEV/SHAPE/TIER_SEV maps) so the React app reuses
// the same colour-vision-safe tier treatment (shape + colour + label).

export type Tier = "low" | "watch" | "high";
export type Severity = "low" | "medium" | "high";
export type RiskType = "attendance" | "academic" | "fee";

export const ACCENT = "#0E7C86";
export const ACCENT_INK = "#0A656D";

export const SEV: Record<Severity, { ink: string; fill: string; bg: string }> = {
  high: { ink: "#B42318", fill: "#B42318", bg: "#FBEAE8" },
  medium: { ink: "#8A5800", fill: "#B07A12", bg: "#FAF0DC" },
  low: { ink: "#1F7A4D", fill: "#1F7A4D", bg: "#E7F4EC" },
};

export const TIER_SEV: Record<Tier, Severity> = { high: "high", watch: "medium", low: "low" };

export function sevForTier(tier: Tier) {
  return SEV[TIER_SEV[tier]];
}

export const TIER_LABEL: Record<Tier, string> = { high: "High", watch: "Watch", low: "Low" };

export const TYPE_LABEL: Record<string, string> = {
  mentor_meeting: "Mentor meeting",
  remedial_class: "Remedial class",
  parent_contact: "Parent contact",
  counselling: "Counselling",
  other: "Other",
};

export const STATUS_LABEL: Record<string, string> = {
  suggested: "Suggested",
  open: "Open",
  in_progress: "In progress",
  completed: "Completed",
  dismissed: "Dismissed",
};

export const OUTCOME_LABEL: Record<string, string> = {
  improved: "Improved",
  no_change: "No change",
  worsened: "Worsened",
  unknown: "Unknown",
};

export const TITLE_HINT: Record<string, string> = {
  mentor_meeting: "e.g. 1:1 check-in on attendance",
  remedial_class: "e.g. Extra DBMS problem session",
  parent_contact: "e.g. Call guardian about attendance",
  counselling: "e.g. Refer to student wellbeing cell",
  other: "Describe the action",
};

export const RISK_TYPE_LABEL: Record<RiskType, string> = {
  attendance: "Attendance",
  academic: "Academic",
  fee: "Fee",
};
