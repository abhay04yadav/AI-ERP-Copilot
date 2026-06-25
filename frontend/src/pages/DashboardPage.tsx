import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { getRiskSummary, getRiskSummaryByDepartment, listAtRiskStudents } from "../api/risk";
import { ErrorState, LoadingState } from "../design/States";
import { TierBadge } from "../design/TierBadge";
import { sevForTier, type Tier } from "../design/tokens";

export function DashboardPage() {
  const navigate = useNavigate();

  const summaryQuery = useQuery({ queryKey: ["risk-summary"], queryFn: getRiskSummary });
  const byDeptQuery = useQuery({ queryKey: ["risk-summary-by-department"], queryFn: getRiskSummaryByDepartment });
  const topQuery = useQuery({
    queryKey: ["risk-students", "high", "all"],
    queryFn: () => listAtRiskStudents({ tier: "high" }),
  });

  if (summaryQuery.isLoading || byDeptQuery.isLoading) {
    return <LoadingState label="Loading institution overview…" />;
  }
  if (summaryQuery.isError || byDeptQuery.isError || !summaryQuery.data || !byDeptQuery.data) {
    return (
      <div className="main-pad" style={{ padding: "30px 36px 60px", maxWidth: 1100, width: "100%" }}>
        <ErrorState
          title="Dashboard didn't load"
          message="The risk service didn't respond. Try again in a moment."
          onRetry={() => {
            summaryQuery.refetch();
            byDeptQuery.refetch();
          }}
        />
      </div>
    );
  }

  const summary = summaryQuery.data;
  const total = summary.total_assessed;
  const pct = (n: number) => (total > 0 ? `${((n / total) * 100).toFixed(1)}% of assessed` : "—");
  const departments = [...byDeptQuery.data.departments].sort((a, b) => b.high / Math.max(1, b.total) - a.high / Math.max(1, a.total));
  const maxRate = Math.max(0.0001, ...departments.map((d) => d.high / Math.max(1, d.total)));
  const topStudents = (topQuery.data ?? []).slice(0, 5);

  const kpis: { label: string; value: number; sub: string; tier?: Tier }[] = [
    { label: "Assessed", value: total, sub: `across ${departments.length} departments` },
    { label: "High risk", value: summary.by_tier.high, sub: pct(summary.by_tier.high), tier: "high" },
    { label: "Watch", value: summary.by_tier.watch, sub: pct(summary.by_tier.watch), tier: "watch" },
    { label: "Low", value: summary.by_tier.low, sub: pct(summary.by_tier.low), tier: "low" },
  ];

  return (
    <div className="main-pad" style={{ padding: "30px 36px 60px", maxWidth: 1100, width: "100%" }}>
      <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".07em", color: "#A2ACB8", marginBottom: 7 }}>
        LEADERSHIP · WHOLE INSTITUTION
      </div>
      <h1 style={{ margin: 0, fontSize: 25, fontWeight: 800, letterSpacing: "-.02em" }}>Institution overview</h1>
      <p className="tnum" style={{ margin: "6px 0 0", fontSize: 13.5, color: "#6B7686", fontWeight: 500 }}>
        <span style={{ fontWeight: 700, color: "#16202C" }}>{total}</span> students assessed across{" "}
        {departments.length} departments
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14, marginTop: 22 }}>
        {kpis.map((k) => (
          <div key={k.label} className="card" style={{ padding: "17px 19px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {k.tier && <span className={`shape-${k.tier}`} />}
              <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: ".02em", color: "#6B7686" }}>{k.label}</span>
            </div>
            <div
              className="tnum"
              style={{
                fontWeight: 800,
                fontSize: 30,
                color: k.tier ? sevForTier(k.tier).ink : "#16202C",
                lineHeight: 1.05,
                marginTop: 9,
                letterSpacing: "-.02em",
              }}
            >
              {k.value}
            </div>
            <div className="tnum" style={{ fontSize: 11.5, color: "#9AA4B1", fontWeight: 600, marginTop: 3 }}>
              {k.sub}
            </div>
          </div>
        ))}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Risk distribution</h2>
          <span style={{ fontSize: 11.5, color: "#9AA4B1", fontWeight: 600 }}>advisory tiers · the human decides</span>
        </div>
        <div style={{ marginTop: 15, height: 15, borderRadius: 8, overflow: "hidden", display: "flex" }}>
          <span style={{ flex: summary.by_tier.high || 0.0001, background: "#B42318" }} />
          <span style={{ flex: summary.by_tier.watch || 0.0001, background: "#B07A12" }} />
          <span style={{ flex: summary.by_tier.low || 0.0001, background: "#1F7A4D" }} />
        </div>
        <div style={{ display: "flex", gap: 26, marginTop: 14, flexWrap: "wrap" }}>
          {(["high", "watch", "low"] as Tier[]).map((tier) => (
            <div key={tier} style={{ display: "flex", alignItems: "center", gap: 9 }}>
              <span className={`shape-${tier}`} />
              <span style={{ fontSize: 12.5, fontWeight: 700, color: "#16202C" }}>{tier === "high" ? "High" : tier === "watch" ? "Watch" : "Low"}</span>
              <span className="tnum" style={{ fontSize: 12.5, fontWeight: 700, color: "#16202C" }}>{summary.by_tier[tier]}</span>
              <span className="tnum" style={{ fontSize: 11.5, color: "#9AA4B1", fontWeight: 600 }}>{pct(summary.by_tier[tier])}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Risk trend over time</h2>
        <p style={{ margin: "10px 0 0", fontSize: 13, color: "#8A95A2", lineHeight: 1.5 }}>
          Trend builds as risk data accumulates. Check back after a few recompute cycles to see the institution's
          risk trajectory.
        </p>
      </div>

      <div className="grid-2" style={{ display: "grid", gridTemplateColumns: "1.15fr 1fr", gap: 20, marginTop: 16, alignItems: "start" }}>
        <section className="card">
          <h2 style={{ margin: "0 0 3px", fontSize: 15, fontWeight: 700 }}>By department</h2>
          <p style={{ margin: "0 0 16px", fontSize: 12, color: "#8A95A2", fontWeight: 500 }}>
            Ranked by share of students at high risk
          </p>
          <div style={{ display: "flex", flexDirection: "column" }}>
            {departments.map((d) => {
              const rate = d.high / Math.max(1, d.total);
              return (
                <div
                  key={d.department}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "130px 1fr auto",
                    gap: 14,
                    alignItems: "center",
                    padding: "11px 0",
                    borderTop: "1px solid #EDF1F4",
                  }}
                >
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                      <span style={{ fontWeight: 700, fontSize: 13.5, color: "#16202C" }}>{d.department}</span>
                      {d.department === "Unassigned" && (
                        <span
                          title="No department resolved for these students — not the same as 'no mentor'"
                          style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".03em", color: "#8A6A22", background: "#FBF3DE", borderRadius: 5, padding: "1px 5px" }}
                        >
                          NO DEPARTMENT
                        </span>
                      )}
                    </div>
                    <div className="tnum" style={{ fontSize: 11, color: "#9AA4B1", fontWeight: 600, marginTop: 1 }}>
                      {d.total} students
                    </div>
                  </div>
                  <div style={{ position: "relative", height: 8, background: "#F0F3F5", borderRadius: 4 }}>
                    <span style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${(rate / maxRate) * 100}%`, background: "#B42318", borderRadius: 4 }} />
                  </div>
                  <div style={{ textAlign: "right", minWidth: 96 }}>
                    <span className="tnum" style={{ fontWeight: 800, fontSize: 14, color: "#B42318" }}>{d.high}</span>
                    <span style={{ fontSize: 11.5, color: "#9AA4B1", fontWeight: 600 }}> high</span>
                    <span className="tnum" style={{ fontSize: 11.5, color: "#9AA4B1", fontWeight: 600 }}> · {(rate * 100).toFixed(1)}%</span>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <section className="card">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Highest risk right now</h2>
            <button className="btn-link" onClick={() => navigate("/board")}>
              Open board →
            </button>
          </div>
          <p className="tnum" style={{ margin: "6px 0 14px", fontSize: 12, color: "#8A95A2", fontWeight: 500 }}>
            Top of {summary.by_tier.high} high-risk students · click to open 360
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            {topStudents.map((s) => {
              const sev = sevForTier("high");
              return (
                <div
                  key={s.student_id}
                  role="button"
                  tabIndex={0}
                  onClick={() => navigate(`/students/${s.student_id}`)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") navigate(`/students/${s.student_id}`);
                  }}
                  style={{ display: "flex", alignItems: "center", gap: 12, border: "1px solid #EDF1F4", borderRadius: 10, padding: "11px 13px", cursor: "pointer" }}
                >
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <span style={{ fontWeight: 700, fontSize: 13.5, color: "#16202C" }}>{s.name}</span>
                      <span className="tnum" style={{ fontSize: 11, color: "#9AA4B1", fontWeight: 600 }}>{s.canonical_roll_no}</span>
                    </div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 11, flex: "none" }}>
                    <TierBadge tier="high" />
                    <span className="tnum" style={{ color: sev.ink, fontWeight: 800, fontSize: 20 }}>{Math.round(s.overall_score)}</span>
                  </div>
                </div>
              );
            })}
            {topStudents.length === 0 && <p style={{ margin: 0, fontSize: 13, color: "#8A95A2" }}>No high-risk students right now.</p>}
          </div>
        </section>
      </div>
    </div>
  );
}
