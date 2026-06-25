import type { RiskFindingResponse } from "../api/types";
import { findingViewModel } from "./findingViewModel";

export function FindingRowCompact({ finding }: { finding: RiskFindingResponse }) {
  const vm = findingViewModel(finding);
  const sev = severityColors(vm.severity);
  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12 }}>
        <span style={{ fontSize: 13, color: "#3A4654", fontWeight: 500, minWidth: 0 }}>
          <span style={{ fontWeight: 700, fontSize: 9.5, letterSpacing: ".06em", color: "#A2ACB8", marginRight: 7 }}>
            {vm.typeTag}
          </span>
          {vm.message}
        </span>
        <span className="tnum" style={{ color: sev.ink, fontWeight: 700, fontSize: 13, whiteSpace: "nowrap" }}>
          {vm.metricBig}
        </span>
      </div>
      {vm.isMeter && vm.meterPct !== null && vm.meterThresholdPct !== null && (
        <div style={{ marginTop: 5, position: "relative", height: 5, background: "#EAEEF1", borderRadius: 3 }}>
          <span
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              bottom: 0,
              width: `${Math.min(100, vm.meterPct)}%`,
              background: sev.fill,
              borderRadius: 4,
            }}
          />
          <span
            style={{
              position: "absolute",
              left: `${Math.min(100, vm.meterThresholdPct)}%`,
              top: -3,
              bottom: -3,
              width: 2,
              background: "#2A3340",
              borderRadius: 1,
            }}
          />
        </div>
      )}
    </div>
  );
}

export function FindingCardFull({ finding }: { finding: RiskFindingResponse }) {
  const vm = findingViewModel(finding);
  const sev = severityColors(vm.severity);
  return (
    <div style={{ border: "1px solid #EDF1F4", borderRadius: 11, padding: "15px 16px" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 14 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ width: 9, height: 9, borderRadius: 2, background: sev.fill, flex: "none", marginTop: 4 }} />
            <span style={{ fontWeight: 700, fontSize: 14, color: "#16202C" }}>{vm.headline}</span>
            <span
              style={{
                fontSize: 9.5,
                fontWeight: 700,
                letterSpacing: ".04em",
                padding: "1px 6px",
                borderRadius: 5,
                background: sev.bg,
                color: sev.ink,
              }}
            >
              {vm.severity.charAt(0).toUpperCase() + vm.severity.slice(1)}
            </span>
          </div>
          <p style={{ margin: "7px 0 0 17px", fontSize: 13, color: "#5A6573", fontWeight: 500 }}>{vm.message}</p>
        </div>
        <div style={{ textAlign: "right", flex: "none" }}>
          <div className="tnum" style={{ color: sev.ink, fontWeight: 800, fontSize: 21, lineHeight: 1, letterSpacing: "-.01em" }}>
            {vm.metricBig}
          </div>
          <div className="tnum" style={{ fontSize: 11, color: "#9AA4B1", fontWeight: 600, marginTop: 3 }}>
            {vm.metricSub}
          </div>
        </div>
      </div>
      {vm.isMeter && vm.meterPct !== null && vm.meterThresholdPct !== null && (
        <div style={{ marginTop: 13, marginLeft: 17 }}>
          <div style={{ position: "relative", height: 7, background: "#EAEEF1", borderRadius: 4 }}>
            <span
              style={{
                position: "absolute",
                left: 0,
                top: 0,
                bottom: 0,
                width: `${Math.min(100, vm.meterPct)}%`,
                background: sev.fill,
                borderRadius: 4,
              }}
            />
            <span
              style={{
                position: "absolute",
                left: `${Math.min(100, vm.meterThresholdPct)}%`,
                top: -3,
                bottom: -3,
                width: 2,
                background: "#2A3340",
                borderRadius: 1,
              }}
            />
          </div>
          <div className="tnum" style={{ fontSize: 11, color: "#9AA4B1", fontWeight: 600, marginTop: 6 }}>
            {vm.meterCaption}
          </div>
        </div>
      )}
      {vm.isDelta && (
        <div style={{ marginTop: 11, marginLeft: 17, display: "flex", alignItems: "center", gap: 10 }}>
          <span className="tnum" style={{ fontWeight: 700, fontSize: 13, color: "#5A6573" }}>
            {vm.fromTo}
          </span>
          <span
            className="tnum"
            style={{ fontSize: 11, fontWeight: 700, padding: "2px 7px", borderRadius: 5, background: sev.bg, color: sev.ink }}
          >
            ▼ {vm.deltaText}
          </span>
        </div>
      )}
    </div>
  );
}

function severityColors(severity: "low" | "medium" | "high") {
  if (severity === "high") return { ink: "#B42318", fill: "#B42318", bg: "#FBEAE8" };
  if (severity === "low") return { ink: "#1F7A4D", fill: "#1F7A4D", bg: "#E7F4EC" };
  return { ink: "#8A5800", fill: "#B07A12", bg: "#FAF0DC" };
}
