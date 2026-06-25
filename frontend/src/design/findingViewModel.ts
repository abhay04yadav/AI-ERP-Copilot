import type { RiskFindingResponse } from "../api/types";
import { SEV, type Severity } from "./tokens";

export interface FindingViewModel {
  typeTag: string;
  message: string;
  severity: Severity;
  headline: string;
  metricBig: string;
  metricSub: string;
  isMeter: boolean;
  meterPct: number | null;
  meterThresholdPct: number | null;
  meterCaption: string;
  isDelta: boolean;
  fromTo: string;
  deltaText: string;
}

// Mirrors the design's findingVM() switch on finding code, reading the
// engine's actual evidence shape per rule (app/services/risk/rules/*.py)
// instead of the mockup's illustrative ev fields.
export function findingViewModel(finding: RiskFindingResponse): FindingViewModel {
  const evidence = finding.evidence as Record<string, number>;

  const base: FindingViewModel = {
    typeTag: finding.risk_type.toUpperCase(),
    message: finding.message,
    severity: finding.severity as Severity,
    headline: finding.code,
    metricBig: "",
    metricSub: "",
    isMeter: false,
    meterPct: null,
    meterThresholdPct: null,
    meterCaption: "",
    isDelta: false,
    fromTo: "",
    deltaText: "",
  };

  switch (finding.code) {
    case "ATTENDANCE_BELOW_THRESHOLD": {
      const value = evidence.value;
      const threshold = evidence.threshold;
      return {
        ...base,
        headline: "Attendance below minimum",
        metricBig: `${value}%`,
        metricSub: `min ${threshold}%`,
        isMeter: true,
        meterPct: value,
        meterThresholdPct: threshold,
        meterCaption: `${Math.round((threshold - value) * 100) / 100} points under the ${threshold}% line`,
      };
    }
    case "ATTENDANCE_DECLINING": {
      const from = evidence.prior_pct;
      const to = evidence.recent_pct;
      return {
        ...base,
        headline: "Attendance falling",
        metricBig: `${to}%`,
        metricSub: `was ${from}%`,
        isDelta: true,
        fromTo: `${from}% → ${to}%`,
        deltaText: `-${Math.round((from - to) * 100) / 100} pts`,
      };
    }
    case "ACADEMIC_DECLINE": {
      const from = evidence.baseline_pct;
      const to = evidence.latest_pct;
      return {
        ...base,
        headline: "Marks declining",
        metricBig: `${to}%`,
        metricSub: `was ${from}%`,
        isDelta: true,
        fromTo: `${from}% → ${to}%`,
        deltaText: `-${Math.round((from - to) * 100) / 100} pts`,
      };
    }
    case "ACADEMIC_FAILING_INTERNALS": {
      const count = evidence.failing_count;
      const threshold = evidence.threshold;
      return {
        ...base,
        headline: "Failing internals",
        metricBig: String(count),
        metricSub: `below ${threshold}%`,
      };
    }
    case "FEE_OVERDUE": {
      const days = evidence.overdue_days;
      return {
        ...base,
        headline: "Fees overdue",
        metricBig: `${days}d`,
        metricSub: "pending",
      };
    }
    default:
      return { ...base, headline: finding.code };
  }
}

export { SEV };
