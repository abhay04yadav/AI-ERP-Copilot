import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { listAlerts, markAlertRead } from "../api/risk";
import { sevForTier, TIER_LABEL, type Tier } from "../design/tokens";

const UNREAD_STATUSES = new Set(["pending", "sent"]);

const REASON_LABEL: Record<string, string> = {
  tier_entered_high: "Newly entered high risk",
  tier_escalated_to_high: "Escalated to high risk",
};

export function AlertsBell() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: alerts = [] } = useQuery({
    queryKey: ["alerts"],
    queryFn: () => listAlerts(),
    refetchInterval: 60_000,
  });

  const markRead = useMutation({
    mutationFn: markAlertRead,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });

  const unreadCount = alerts.filter((a) => UNREAD_STATUSES.has(a.status)).length;

  function openAlert(studentId: string, alertId: string) {
    setOpen(false);
    markRead.mutate(alertId);
    navigate(`/students/${studentId}`);
  }

  return (
    <div style={{ position: "relative" }}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label={`Alerts${unreadCount > 0 ? `, ${unreadCount} unread` : ""}`}
        style={{
          position: "relative",
          width: 40,
          height: 40,
          borderRadius: 9,
          border: `1px solid ${open ? "#0E7C86" : "#E1E7EC"}`,
          background: open ? "#E3F1F2" : "#fff",
          color: open ? "#0A656D" : "#5A6573",
          fontSize: 17,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flex: "none",
        }}
      >
        ⚑
        {unreadCount > 0 && (
          <span
            style={{
              position: "absolute",
              top: -5,
              right: -5,
              minWidth: 18,
              height: 18,
              padding: "0 4px",
              borderRadius: 9,
              background: "#B42318",
              color: "#fff",
              fontSize: 10,
              fontWeight: 800,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              border: "2px solid #E9EDF0",
            }}
            className="tnum"
          >
            {unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            top: 50,
            right: 0,
            width: 340,
            background: "#fff",
            border: "1px solid #E1E7EC",
            borderRadius: 13,
            boxShadow: "0 16px 44px rgba(20,30,45,.2)",
            zIndex: 45,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              padding: "14px 16px",
              borderBottom: "1px solid #EDF1F4",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <div>
              <div style={{ fontWeight: 800, fontSize: 14 }}>Risk alerts</div>
              <div style={{ fontSize: 11.5, color: "#8A95A2", fontWeight: 600 }}>
                Students who crossed into a higher tier
              </div>
            </div>
            <button
              onClick={() => setOpen(false)}
              aria-label="Close"
              style={{ width: 26, height: 26, borderRadius: 7, color: "#9AA4B1", fontSize: 14 }}
            >
              ✕
            </button>
          </div>
          <div style={{ maxHeight: 330, overflow: "auto" }}>
            {alerts.length === 0 && (
              <div style={{ padding: 24, textAlign: "center", fontSize: 13, color: "#8A95A2" }}>
                No alerts yet.
              </div>
            )}
            {alerts.map((alert) => {
              const newTier = (alert.payload?.new_tier as Tier | undefined) ?? "high";
              const previousTier = alert.payload?.previous_tier as Tier | null | undefined;
              const score = alert.payload?.overall_score as number | undefined;
              const sev = sevForTier(newTier);
              return (
                <div
                  key={alert.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => openAlert(alert.student_id, alert.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      openAlert(alert.student_id, alert.id);
                    }
                  }}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "13px 16px",
                    borderBottom: "1px solid #F2F5F7",
                    cursor: "pointer",
                    background: UNREAD_STATUSES.has(alert.status) ? "#FAFCFC" : "#fff",
                  }}
                >
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontWeight: 700, fontSize: 13.5, color: "#16202C" }}>
                      {REASON_LABEL[alert.reason] ?? alert.reason}
                    </div>
                    <div style={{ fontSize: 11, color: "#9AA4B1", fontWeight: 600, marginTop: 1 }}>
                      {new Date(alert.created_at).toLocaleString()}
                    </div>
                    <div style={{ marginTop: 7 }}>
                      <span
                        className="badge"
                        style={{ background: sev.bg, color: sev.ink }}
                      >
                        {previousTier ? `${TIER_LABEL[previousTier]} → ` : ""}
                        {TIER_LABEL[newTier]}
                      </span>
                    </div>
                  </div>
                  {score !== undefined && (
                    <span className="tnum" style={{ color: sev.ink, fontWeight: 800, fontSize: 17 }}>
                      {Math.round(score)}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
