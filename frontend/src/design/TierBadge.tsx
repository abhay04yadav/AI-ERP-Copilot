import { sevForTier, TIER_LABEL, type Tier } from "./tokens";

export function TierBadge({ tier, big = false }: { tier: Tier; big?: boolean }) {
  const sev = sevForTier(tier);
  return (
    <span
      className={`badge${big ? " badge-big" : ""}`}
      style={{ background: sev.bg, color: sev.ink }}
    >
      <span className={`shape-${tier}`} />
      {TIER_LABEL[tier].toUpperCase()}
    </span>
  );
}
