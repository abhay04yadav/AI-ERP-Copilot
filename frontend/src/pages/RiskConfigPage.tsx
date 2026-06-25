import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { getRiskConfig, updateRiskConfig } from "../api/risk";
import { ErrorState, LoadingState } from "../design/States";
import { useToast } from "../design/ToastContext";

const WEIGHT_KEYS = [
  "ATTENDANCE_BELOW_THRESHOLD",
  "ATTENDANCE_DECLINING",
  "ACADEMIC_FAILING_INTERNALS",
  "ACADEMIC_DECLINE",
  "FEE_OVERDUE",
] as const;

interface ConfigFormState {
  attendance_threshold_pct: number;
  attendance_min_sessions: number;
  attendance_trend_window: number;
  attendance_decline_points: number;
  academic_fail_pct: number;
  academic_decline_points: number;
  fee_overdue_days: number;
  weights: Record<string, number>;
  tier_cutoffs: { watch: number; high: number };
}

function field(label: string, value: number, onChange: (n: number) => void, opts?: { min?: number; max?: number }) {
  return (
    <label style={{ fontSize: 12, fontWeight: 700, color: "#5A6573", display: "block" }}>
      {label}
      <input
        type="number"
        value={value}
        min={opts?.min}
        max={opts?.max}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{
          display: "block",
          width: "100%",
          marginTop: 6,
          border: "1px solid #DDE4E9",
          borderRadius: 9,
          padding: "9px 12px",
          fontSize: 14,
        }}
      />
    </label>
  );
}

export function RiskConfigPage() {
  const queryClient = useQueryClient();
  const flashToast = useToast();
  const configQuery = useQuery({ queryKey: ["risk-config"], queryFn: getRiskConfig });
  const [form, setForm] = useState<ConfigFormState | null>(null);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);

  useEffect(() => {
    if (configQuery.data && !form) {
      setForm(configQuery.data.config as unknown as ConfigFormState);
    }
  }, [configQuery.data, form]);

  const save = useMutation({
    mutationFn: (config: ConfigFormState) => updateRiskConfig({ config: config as never }),
    onSuccess: (data) => {
      queryClient.setQueryData(["risk-config"], data);
      flashToast(`Saved — version ${data.version}`);
      setValidationErrors([]);
    },
    onError: (error: unknown) => {
      const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      if (Array.isArray(detail)) {
        setValidationErrors(detail.map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).join(".")}: ${d.msg}`));
      } else {
        setValidationErrors(["Couldn't save. Check that watch < high and all values are in range."]);
      }
    },
  });

  if (configQuery.isLoading) return <LoadingState label="Loading risk config…" />;
  if (configQuery.isError || !form) {
    return (
      <div className="main-pad" style={{ padding: "30px 36px 60px", maxWidth: 760, width: "100%" }}>
        <ErrorState title="Couldn't load risk config" message="Try again in a moment." onRetry={() => configQuery.refetch()} />
      </div>
    );
  }

  return (
    <div className="main-pad" style={{ padding: "30px 36px 60px", maxWidth: 760, width: "100%" }}>
      <h1 style={{ margin: 0, fontSize: 25, fontWeight: 800, letterSpacing: "-.02em" }}>Risk config</h1>
      <p style={{ margin: "6px 0 0", fontSize: 13.5, color: "#6B7686", fontWeight: 500 }}>
        Version {configQuery.data?.version} · these thresholds drive every score and tier computed by the engine.
      </p>

      <div className="card" style={{ marginTop: 22, display: "flex", flexDirection: "column", gap: 16 }}>
        <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Attendance</h2>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          {field("Threshold % (below this fires a finding)", form.attendance_threshold_pct, (n) =>
            setForm({ ...form, attendance_threshold_pct: n }),
          )}
          {field("Min sessions before the rule fires", form.attendance_min_sessions, (n) =>
            setForm({ ...form, attendance_min_sessions: n }),
          )}
          {field("Trend window (sessions)", form.attendance_trend_window, (n) =>
            setForm({ ...form, attendance_trend_window: n }),
          )}
          {field("Decline points to flag a drop", form.attendance_decline_points, (n) =>
            setForm({ ...form, attendance_decline_points: n }),
          )}
        </div>

        <h2 style={{ margin: "8px 0 0", fontSize: 15, fontWeight: 700 }}>Academic</h2>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          {field("Fail % (internal mark below this)", form.academic_fail_pct, (n) => setForm({ ...form, academic_fail_pct: n }))}
          {field("Decline points to flag a drop", form.academic_decline_points, (n) =>
            setForm({ ...form, academic_decline_points: n }),
          )}
        </div>

        <h2 style={{ margin: "8px 0 0", fontSize: 15, fontWeight: 700 }}>Fees</h2>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          {field("Overdue days threshold", form.fee_overdue_days, (n) => setForm({ ...form, fee_overdue_days: n }))}
        </div>

        <h2 style={{ margin: "8px 0 0", fontSize: 15, fontWeight: 700 }}>Weights</h2>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          {WEIGHT_KEYS.map((key) =>
            field(key.replace(/_/g, " "), form.weights[key] ?? 0, (n) =>
              setForm({ ...form, weights: { ...form.weights, [key]: n } }),
            ),
          )}
        </div>

        <h2 style={{ margin: "8px 0 0", fontSize: 15, fontWeight: 700 }}>Tier cutoffs</h2>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          {field("Watch (score ≥)", form.tier_cutoffs.watch, (n) =>
            setForm({ ...form, tier_cutoffs: { ...form.tier_cutoffs, watch: n } }),
          )}
          {field("High (score ≥)", form.tier_cutoffs.high, (n) =>
            setForm({ ...form, tier_cutoffs: { ...form.tier_cutoffs, high: n } }),
          )}
        </div>

        {form.tier_cutoffs.watch >= form.tier_cutoffs.high && (
          <div style={{ color: "#B42318", fontSize: 13, fontWeight: 600 }}>
            Watch must be strictly less than high.
          </div>
        )}
        {validationErrors.length > 0 && (
          <ul style={{ color: "#B42318", fontSize: 13, fontWeight: 600, margin: 0, paddingLeft: 18 }}>
            {validationErrors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        )}

        <div>
          <button
            className="btn-primary"
            disabled={save.isPending || form.tier_cutoffs.watch >= form.tier_cutoffs.high}
            onClick={() => save.mutate(form)}
          >
            {save.isPending ? "Saving…" : "Save changes"}
          </button>
        </div>
      </div>
    </div>
  );
}
