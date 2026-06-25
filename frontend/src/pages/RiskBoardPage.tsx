import { useQueries } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { listAtRiskStudents } from "../api/risk";
import type { AtRiskStudentResponse } from "../api/types";
import { EmptyState, ErrorState, LoadingState } from "../design/States";
import { TierBadge } from "../design/TierBadge";
import { sevForTier, type Tier } from "../design/tokens";
import { LogInterventionModal } from "../design/LogInterventionModal";

const TIERS: Tier[] = ["high", "watch", "low"];
const TYPES = [
  { key: "all", label: "All" },
  { key: "attendance", label: "Attendance" },
  { key: "academic", label: "Academic" },
  { key: "fee", label: "Fee" },
];
const PAGE_SIZE_CAP = 50;

export function RiskBoardPage() {
  const navigate = useNavigate();
  const [tierFilter, setTierFilter] = useState<Record<Tier, boolean>>({ high: true, watch: true, low: false });
  const [typeFilter, setTypeFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [logTarget, setLogTarget] = useState<AtRiskStudentResponse | null>(null);

  const selectedTiers = TIERS.filter((t) => tierFilter[t]);
  const useDefaultAtRisk = tierFilter.high && tierFilter.watch && !tierFilter.low;

  const queries = useQueries({
    queries: useDefaultAtRisk
      ? [
          {
            queryKey: ["risk-students", "default", typeFilter],
            queryFn: () =>
              listAtRiskStudents({ risk_type: typeFilter === "all" ? undefined : typeFilter }),
          },
        ]
      : selectedTiers.map((tier) => ({
          queryKey: ["risk-students", tier, typeFilter],
          queryFn: () =>
            listAtRiskStudents({ tier, risk_type: typeFilter === "all" ? undefined : typeFilter }),
        })),
  });

  const isLoading = selectedTiers.length > 0 && queries.some((q) => q.isLoading);
  const isError = queries.some((q) => q.isError);
  const anyAtCap = queries.some((q) => (q.data?.length ?? 0) >= PAGE_SIZE_CAP);

  const students = useMemo(() => {
    const merged = new Map<string, AtRiskStudentResponse>();
    for (const q of queries) {
      for (const s of q.data ?? []) {
        merged.set(s.student_id, s);
      }
    }
    return Array.from(merged.values()).sort((a, b) => b.overall_score - a.overall_score);
  }, [queries]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return students;
    return students.filter(
      (s) => s.name.toLowerCase().includes(q) || s.canonical_roll_no.toLowerCase().includes(q),
    );
  }, [students, search]);

  function retry() {
    queries.forEach((q) => q.refetch());
  }

  return (
    <div className="main-pad" style={{ padding: "30px 36px 60px", maxWidth: 1080, width: "100%" }}>
      <header style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 20, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 25, fontWeight: 800, letterSpacing: "-.02em" }}>At-risk students</h1>
          <p className="tnum" style={{ margin: "6px 0 0", fontSize: 13.5, color: "#6B7686", fontWeight: 500 }}>
            <span className="tnum">{filtered.length}</span> shown
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, background: "#fff", border: "1px solid #E1E7EC", borderRadius: 9, padding: "0 11px", minWidth: 248 }}>
          <span style={{ fontSize: 14, color: "#9AA4B1" }}>⌕</span>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name or roll number"
            style={{ border: "none", background: "none", outline: "none", padding: "10px 0", fontSize: 13, color: "#16202C", width: "100%" }}
          />
          {search && (
            <button onClick={() => setSearch("")} aria-label="Clear search" style={{ color: "#9AA4B1", fontSize: 13, flex: "none" }}>
              ✕
            </button>
          )}
        </div>
      </header>

      <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 22, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".06em", color: "#A2ACB8", marginRight: 2 }}>TIER</span>
          {TIERS.map((tier) => (
            <button
              key={tier}
              onClick={() => setTierFilter((f) => ({ ...f, [tier]: !f[tier] }))}
              style={
                tierFilter[tier]
                  ? { display: "inline-flex", alignItems: "center", gap: 6, padding: "6px 11px", borderRadius: 8, border: "1.5px solid #0E7C86", background: "#fff", color: "#16202C", fontWeight: 700, fontSize: 12.5 }
                  : { display: "inline-flex", alignItems: "center", gap: 6, padding: "6px 11px", borderRadius: 8, border: "1px solid #E1E7EC", background: "#fff", color: "#9AA4B1", fontWeight: 600, fontSize: 12.5, opacity: 0.75 }
              }
            >
              <span className={`shape-${tier}`} />
              {tier === "high" ? "High" : tier === "watch" ? "Watch" : "Low"}
            </button>
          ))}
        </div>
        <div style={{ width: 1, height: 22, background: "#DDE4E9" }} />
        <div style={{ display: "flex", alignItems: "center", background: "#fff", border: "1px solid #E1E7EC", borderRadius: 9, padding: 3 }}>
          {TYPES.map((t) => (
            <button
              key={t.key}
              onClick={() => setTypeFilter(t.key)}
              style={
                typeFilter === t.key
                  ? { padding: "6px 12px", borderRadius: 7, background: "#E3F1F2", color: "#0A656D", fontWeight: 700, fontSize: 12.5 }
                  : { padding: "6px 12px", borderRadius: 7, background: "transparent", color: "#8A95A2", fontWeight: 600, fontSize: 12.5 }
              }
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {selectedTiers.length === 0 && (
        <div style={{ marginTop: 34, background: "#fff", border: "1px dashed #D7DEE4", borderRadius: 12, padding: 34, textAlign: "center" }}>
          <p style={{ margin: 0, fontSize: 14, color: "#6B7686" }}>Select at least one tier to see students.</p>
        </div>
      )}

      {selectedTiers.length > 0 && isLoading && <LoadingState label="Loading at-risk students…" />}

      {selectedTiers.length > 0 && !isLoading && isError && (
        <ErrorState
          title="Risk scores didn't load"
          message="The risk service didn't respond. Your students are safe in the system — only this view failed. Try again in a moment."
          onRetry={retry}
        />
      )}

      {selectedTiers.length > 0 && !isLoading && !isError && filtered.length === 0 && students.length === 0 && (
        <EmptyState
          title="Nobody in your cohort is flagged"
          message="No students in your scope are at risk right now. We'll surface anyone here the moment their attendance, marks, or fees cross a threshold."
        />
      )}

      {selectedTiers.length > 0 && !isLoading && !isError && filtered.length === 0 && students.length > 0 && (
        <div style={{ marginTop: 34, background: "#fff", border: "1px dashed #D7DEE4", borderRadius: 12, padding: 34, textAlign: "center" }}>
          <p style={{ margin: 0, fontSize: 14, color: "#6B7686" }}>No students match these filters.</p>
          <button
            className="btn-link"
            style={{ marginTop: 10 }}
            onClick={() => {
              setSearch("");
              setTypeFilter("all");
            }}
          >
            Clear filters
          </button>
        </div>
      )}

      {selectedTiers.length > 0 && !isLoading && !isError && filtered.length > 0 && (
        <>
          {anyAtCap && (
            <p style={{ marginTop: 16, fontSize: 12, color: "#9AA4B1" }}>
              Showing up to {PAGE_SIZE_CAP} per tier. Narrow your filters to see more.
            </p>
          )}
          <div style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 12 }}>
            {filtered.map((s) => {
              const sev = sevForTier(s.tier as Tier);
              return (
                <div
                  key={s.student_id}
                  role="button"
                  tabIndex={0}
                  onClick={() => navigate(`/students/${s.student_id}`)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      navigate(`/students/${s.student_id}`);
                    }
                  }}
                  className="row-grid"
                  style={{
                    display: "grid",
                    gridTemplateColumns: "5px 1fr auto",
                    gap: 18,
                    alignItems: "flex-start",
                    background: "#fff",
                    border: "1px solid #E7ECF0",
                    borderRadius: 12,
                    padding: "18px 22px 18px 0",
                    overflow: "hidden",
                    cursor: "pointer",
                    boxShadow: "0 1px 2px rgba(20,30,45,.04)",
                  }}
                >
                  <span style={{ background: sev.fill, alignSelf: "stretch", borderRadius: "0 3px 3px 0" }} />
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                      <span style={{ fontWeight: 700, fontSize: 15.5, color: "#16202C" }}>{s.name}</span>
                      <span className="tnum" style={{ fontWeight: 600, fontSize: 12, color: "#828D9B" }}>
                        {s.canonical_roll_no}
                      </span>
                    </div>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", justifyContent: "space-between", minWidth: 92, gap: 10 }}>
                    <div style={{ textAlign: "right" }}>
                      <TierBadge tier={s.tier as Tier} />
                      <div className="tnum" style={{ color: sev.ink, fontWeight: 800, fontSize: 30, lineHeight: 1, marginTop: 9, letterSpacing: "-.02em" }}>
                        {Math.round(s.overall_score)}
                      </div>
                    </div>
                    <button
                      className="btn-ghost"
                      onClick={(e) => {
                        e.stopPropagation();
                        setLogTarget(s);
                      }}
                    >
                      Log intervention
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {logTarget && (
        <LogInterventionModal
          studentId={logTarget.student_id}
          studentName={logTarget.name}
          needsGuardianConsent
          onClose={() => setLogTarget(null)}
        />
      )}
    </div>
  );
}
