import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { getStudentRisk, listInterventions, recordOutcome, updateIntervention } from "../api/risk";
import { getStudent360 } from "../api/students";
import type { InterventionResponse } from "../api/types";
import { FindingCardFull } from "../design/FindingCard";
import { LogInterventionModal } from "../design/LogInterventionModal";
import { ErrorState, LoadingState } from "../design/States";
import { TierBadge } from "../design/TierBadge";
import { useToast } from "../design/ToastContext";
import { OUTCOME_LABEL, sevForTier, STATUS_LABEL, TYPE_LABEL, type Tier } from "../design/tokens";

export function StudentPage() {
  const { studentId } = useParams<{ studentId: string }>();
  const navigate = useNavigate();
  const flashToast = useToast();
  const queryClient = useQueryClient();
  const [showLog, setShowLog] = useState(false);
  const [outcomePickerFor, setOutcomePickerFor] = useState<string | null>(null);

  const profileQuery = useQuery({
    queryKey: ["student-360", studentId],
    queryFn: () => getStudent360(studentId!),
    enabled: !!studentId,
  });
  const riskQuery = useQuery({
    queryKey: ["risk-student-detail", studentId],
    queryFn: () => getStudentRisk(studentId!),
    enabled: !!studentId,
  });
  const interventionsQuery = useQuery({
    queryKey: ["interventions", studentId],
    queryFn: () => listInterventions(studentId!),
    enabled: !!studentId,
  });

  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => updateIntervention(id, { status }),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({ queryKey: ["interventions", studentId] });
      flashToast(
        vars.status === "in_progress"
          ? "Marked in progress"
          : vars.status === "completed"
            ? "Marked complete — record the outcome"
            : vars.status === "dismissed"
              ? "Intervention dismissed"
              : "Updated",
      );
    },
  });

  const setOutcome = useMutation({
    mutationFn: ({ id, outcome }: { id: string; outcome: string }) => recordOutcome(id, { outcome }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["interventions", studentId] });
      setOutcomePickerFor(null);
      flashToast("Outcome recorded");
    },
  });

  if (!studentId) return null;

  if (profileQuery.isLoading || riskQuery.isLoading) {
    return <LoadingState label="Loading student…" />;
  }
  if (profileQuery.isError || riskQuery.isError || !profileQuery.data) {
    return (
      <div className="main-pad" style={{ padding: "24px 36px 70px", maxWidth: 1080, width: "100%" }}>
        <ErrorState
          title="Couldn't load this student"
          message="The student or risk service didn't respond. Try again in a moment."
          onRetry={() => {
            profileQuery.refetch();
            riskQuery.refetch();
          }}
        />
      </div>
    );
  }

  const profile = profileQuery.data;
  const risk = riskQuery.data!;
  const current = risk.current;
  const tier = (current?.tier as Tier) ?? "low";
  const sev = sevForTier(tier);
  const firstName = profile.name.split(" ")[0];
  const isMinorOrUnknown = current ? current.subject_minor_status !== "adult" : true;

  return (
    <div className="main-pad" style={{ padding: "24px 36px 70px", maxWidth: 1080, width: "100%" }}>
      <button className="btn-link" style={{ display: "inline-flex", alignItems: "center", gap: 6, marginBottom: 18 }} onClick={() => navigate("/board")}>
        ← At-risk students
      </button>

      <div className="grid-2" style={{ display: "grid", gridTemplateColumns: "1.25fr 1fr", gap: 28, background: "#fff", border: "1px solid #E7ECF0", borderRadius: 14, padding: "26px 28px" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 11, flexWrap: "wrap" }}>
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 800, letterSpacing: "-.02em" }}>{profile.name}</h1>
            <span
              style={
                isMinorOrUnknown
                  ? { display: "inline-flex", alignItems: "center", gap: 4, padding: "3px 9px", borderRadius: 7, background: "#EEF1F8", color: "#3A4ED6", fontWeight: 700, fontSize: 11 }
                  : { display: "inline-flex", alignItems: "center", padding: "3px 9px", borderRadius: 7, background: "#F0F3F5", color: "#6B7686", fontWeight: 700, fontSize: 11 }
              }
            >
              {current ? (current.subject_minor_status === "minor" ? "Minor" : current.subject_minor_status === "unknown" ? "DOB unknown" : "Adult") : "—"}
            </span>
          </div>
          <p className="tnum" style={{ margin: "9px 0 0", fontSize: 13.5, color: "#6B7686", fontWeight: 500 }}>
            {profile.canonical_roll_no}
            {profile.admission_year ? ` · Admission ${profile.admission_year}` : ""}
          </p>
          <div style={{ marginTop: 18, display: "flex", gap: 9, flexWrap: "wrap" }}>
            <button className="btn-primary" onClick={() => setShowLog(true)}>
              Log intervention
            </button>
          </div>
        </div>
        <div style={{ borderLeft: "1px solid #EDF1F4", paddingLeft: 26 }} className="score-block">
          <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: ".09em", color: "#A2ACB8" }}>RISK SCORE</div>
          {current ? (
            <>
              <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginTop: 8 }}>
                <div style={{ display: "flex", alignItems: "flex-end", gap: 5 }}>
                  <span className="tnum" style={{ color: sev.ink, fontWeight: 800, fontSize: 50, lineHeight: 0.84, letterSpacing: "-.03em" }}>
                    {Math.round(current.overall_score)}
                  </span>
                  <span style={{ fontWeight: 600, fontSize: 15, color: "#9AA4B1", paddingBottom: 6 }}>/100</span>
                </div>
                <TierBadge tier={tier} big />
              </div>
              <div style={{ marginTop: 18 }}>
                <div style={{ position: "relative", height: 9, borderRadius: 5, overflow: "hidden", display: "flex" }}>
                  <span style={{ flex: 25, background: "#E7F4EC" }} />
                  <span style={{ flex: 25, background: "#FAF0DC" }} />
                  <span style={{ flex: 50, background: "#FBEAE8" }} />
                  <span
                    style={{
                      position: "absolute",
                      left: `calc(${Math.min(100, current.overall_score)}% - 6px)`,
                      top: -2,
                      width: 12,
                      height: 13,
                      borderRadius: 3,
                      background: "#fff",
                      border: `2.5px solid ${sev.ink}`,
                    }}
                  />
                </div>
                <div className="tnum" style={{ display: "flex", justifyContent: "space-between", fontSize: 10, fontWeight: 600, color: "#9AA4B1", marginTop: 6 }}>
                  <span>low</span>
                  <span>watch 25</span>
                  <span>high 50</span>
                  <span>100</span>
                </div>
              </div>
              <div style={{ marginTop: 12, fontSize: 12, color: "#8A95A2", fontWeight: 500 }}>
                Computed {new Date(current.computed_at).toLocaleString()} · advisory, you decide
              </div>
            </>
          ) : (
            <p style={{ marginTop: 8, fontSize: 13, color: "#8A95A2" }}>No risk assessment yet for this student.</p>
          )}
        </div>
      </div>

      <div className="grid-2" style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 20, marginTop: 20, alignItems: "start" }}>
        <section className="card">
          <h2 style={{ margin: "0 0 4px", fontSize: 16, fontWeight: 700 }}>
            {current ? `Why ${firstName} is ${tier} risk` : "No findings"}
          </h2>
          <p className="tnum" style={{ margin: "0 0 18px", fontSize: 12.5, color: "#8A95A2", fontWeight: 500 }}>
            {current ? `${current.findings.length} findings · the evidence behind the score` : "—"}
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {current?.findings.map((f, i) => <FindingCardFull key={i} finding={f} />)}
          </div>
        </section>

        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <section className="card">
            <h2 style={{ margin: "0 0 4px", fontSize: 16, fontWeight: 700 }}>Risk over time</h2>
            {risk.history.length > 0 ? (
              <>
                <p style={{ margin: "0 0 20px", fontSize: 12.5, color: "#8A95A2", fontWeight: 500 }}>
                  {risk.history.length} computed assessment{risk.history.length === 1 ? "" : "s"} on record.
                </p>
                <div style={{ display: "flex", alignItems: "flex-end", gap: 10, height: 120, borderBottom: "1px solid #EDF1F4" }}>
                  {[...risk.history].reverse().map((h) => {
                    const hsev = sevForTier(h.tier as Tier);
                    return (
                      <div key={h.id} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end", height: "100%" }}>
                        <span className="tnum" style={{ color: hsev.ink, fontWeight: 800, fontSize: 13, marginBottom: 5 }}>
                          {Math.round(h.overall_score)}
                        </span>
                        <div style={{ width: "100%", maxWidth: 34, height: Math.max(6, Math.round(h.overall_score)), background: hsev.fill, borderRadius: "4px 4px 0 0", opacity: h.tier === "low" ? 0.65 : 1 }} />
                      </div>
                    );
                  })}
                </div>
                <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
                  {[...risk.history].reverse().map((h) => (
                    <div key={h.id} style={{ flex: 1, textAlign: "center" }}>
                      <TierBadge tier={h.tier as Tier} />
                      <div style={{ fontSize: 10, color: "#9AA4B1", fontWeight: 600, marginTop: 4 }}>
                        {new Date(h.computed_at).toLocaleDateString()}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p style={{ margin: "10px 0 0", fontSize: 13, color: "#8A95A2", lineHeight: 1.5 }}>
                This is the first computed risk assessment for {firstName}. A trajectory will appear here after the
                next import.
              </p>
            )}
          </section>

          <section className="card">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Interventions</h2>
              <button className="btn-link" onClick={() => setShowLog(true)}>
                + Log
              </button>
            </div>
            <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 12 }}>
              {(interventionsQuery.data ?? []).map((iv) => (
                <InterventionRow
                  key={iv.id}
                  intervention={iv}
                  outcomePickerOpen={outcomePickerFor === iv.id}
                  onOpenOutcomePicker={() => setOutcomePickerFor(iv.id)}
                  onSetStatus={(status) => setStatus.mutate({ id: iv.id, status })}
                  onSetOutcome={(outcome) => setOutcome.mutate({ id: iv.id, outcome })}
                />
              ))}
              {(interventionsQuery.data ?? []).length === 0 && (
                <div style={{ border: "1px dashed #D7DEE4", borderRadius: 11, padding: 20, textAlign: "center" }}>
                  <p style={{ margin: 0, fontSize: 13, color: "#8A95A2" }}>No interventions logged yet.</p>
                  <button className="btn-link" style={{ marginTop: 8 }} onClick={() => setShowLog(true)}>
                    Log the first one
                  </button>
                </div>
              )}
            </div>
          </section>
        </div>
      </div>

      {showLog && (
        <LogInterventionModal
          studentId={studentId}
          studentName={profile.name}
          needsGuardianConsent={isMinorOrUnknown}
          onClose={() => setShowLog(false)}
        />
      )}
    </div>
  );
}

function InterventionRow({
  intervention,
  outcomePickerOpen,
  onOpenOutcomePicker,
  onSetStatus,
  onSetOutcome,
}: {
  intervention: InterventionResponse;
  outcomePickerOpen: boolean;
  onOpenOutcomePicker: () => void;
  onSetStatus: (status: string) => void;
  onSetOutcome: (outcome: string) => void;
}) {
  const done = intervention.status === "completed";
  const inProgress = intervention.status === "in_progress";
  const dismissed = intervention.status === "dismissed";
  const stColor = done
    ? { ink: "#1F7A4D", bg: "#E7F4EC" }
    : inProgress
      ? { ink: "#8A5800", bg: "#FAF0DC" }
      : dismissed
        ? { ink: "#8A95A2", bg: "#F0F3F5" }
        : { ink: "#0A656D", bg: "#E3F1F2" };

  return (
    <div style={{ border: "1px solid #EDF1F4", borderRadius: 11, padding: "13px 15px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
        <span style={{ fontWeight: 700, fontSize: 13 }}>{TYPE_LABEL[intervention.type] ?? intervention.type}</span>
        <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: ".03em", padding: "2px 7px", borderRadius: 6, background: stColor.bg, color: stColor.ink }}>
          {STATUS_LABEL[intervention.status] ?? intervention.status}
        </span>
      </div>
      <p style={{ margin: "7px 0 0", fontSize: 13, color: "#5A6573", fontWeight: 500 }}>{intervention.title}</p>
      {intervention.notes && (
        <p style={{ margin: "4px 0 0", fontSize: 12, color: "#8A95A2" }}>{intervention.notes}</p>
      )}
      <div className="tnum" style={{ marginTop: 9, display: "flex", alignItems: "center", gap: 8, fontSize: 11.5, color: "#9AA4B1", fontWeight: 600, flexWrap: "wrap" }}>
        <span>{new Date(intervention.created_at).toLocaleDateString()}</span>
      </div>

      {(intervention.status === "open" || intervention.status === "suggested") && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid #F0F3F5", display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn-ghost" onClick={() => onSetStatus("in_progress")}>
            Start
          </button>
          <button className="btn-ghost" onClick={() => onSetStatus("completed")}>
            Mark complete
          </button>
          <button className="btn-ghost" style={{ color: "#9AA4B1" }} onClick={() => onSetStatus("dismissed")}>
            Dismiss
          </button>
        </div>
      )}
      {inProgress && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid #F0F3F5", display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn-ghost" onClick={() => onSetStatus("completed")}>
            Mark complete
          </button>
        </div>
      )}
      {dismissed && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid #F0F3F5", display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn-ghost" style={{ color: "#9AA4B1" }} onClick={() => onSetStatus("open")}>
            Reopen
          </button>
        </div>
      )}

      {done && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid #F0F3F5" }}>
          {/* outcome is recorded via record_outcome service, never returned on the
              Intervention itself -- so we just expose the picker until the user
              records one, rather than reflecting a stale "has outcome" state. */}
          {!outcomePickerOpen ? (
            <button className="btn-link" onClick={onOpenOutcomePicker}>
              Did it help? Record the outcome
            </button>
          ) : (
            <div>
              <div style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: ".05em", color: "#A2ACB8", marginBottom: 8 }}>
                DID IT HELP? RECORD THE OUTCOME
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {["improved", "no_change", "worsened"].map((o) => (
                  <button key={o} className="btn-ghost" onClick={() => onSetOutcome(o)}>
                    {OUTCOME_LABEL[o]}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
