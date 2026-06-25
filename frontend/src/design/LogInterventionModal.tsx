import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { createIntervention } from "../api/risk";
import { useAuth } from "../auth/AuthContext";
import { TITLE_HINT, TYPE_LABEL } from "./tokens";
import { useToast } from "./ToastContext";

interface Props {
  studentId: string;
  studentName: string;
  needsGuardianConsent: boolean;
  onClose: () => void;
}

const TYPES = Object.keys(TYPE_LABEL);

export function LogInterventionModal({ studentId, studentName, needsGuardianConsent, onClose }: Props) {
  const { user } = useAuth();
  const flashToast = useToast();
  const queryClient = useQueryClient();
  const [type, setType] = useState("mentor_meeting");
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [step, setStep] = useState<"form" | "consent">("form");
  const [consentGiven, setConsentGiven] = useState(false);

  const needsConsentForThisType = type === "parent_contact" && needsGuardianConsent;
  const adultParentNote = type === "parent_contact" && !needsGuardianConsent;
  const firstName = studentName.split(" ")[0];

  const submit = useMutation({
    mutationFn: (guardianConsentConfirmed: boolean) =>
      createIntervention({
        student_id: studentId,
        type,
        title: title.trim() || TYPE_LABEL[type],
        notes: notes.trim() || undefined,
        assigned_to: user?.userId,
        guardian_consent_confirmed: guardianConsentConfirmed,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["risk-students"] });
      queryClient.invalidateQueries({ queryKey: ["risk-student-detail", studentId] });
      queryClient.invalidateQueries({ queryKey: ["interventions", studentId] });
      flashToast("Intervention logged");
      onClose();
    },
  });

  function handlePrimary() {
    if (step === "form" && needsConsentForThisType) {
      setStep("consent");
      return;
    }
    submit.mutate(step === "consent");
  }

  function stop(e: React.MouseEvent) {
    e.stopPropagation();
  }

  if (step === "consent") {
    return (
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(22,30,41,.42)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: 20,
          zIndex: 60,
        }}
      >
        <div
          onClick={stop}
          style={{
            background: "#fff",
            borderRadius: 16,
            width: "100%",
            maxWidth: 460,
            boxShadow: "0 24px 60px rgba(20,30,45,.28)",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              background: "#FBF3DE",
              padding: "20px 24px",
              borderBottom: "1px solid #EBDCB4",
              display: "flex",
              alignItems: "center",
              gap: 12,
            }}
          >
            <span
              style={{
                width: 34,
                height: 34,
                borderRadius: 9,
                background: "#E2BE5E",
                color: "#5C420C",
                fontWeight: 800,
                fontSize: 16,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flex: "none",
              }}
            >
              ◆
            </span>
            <div>
              <h2 style={{ margin: 0, fontSize: 16, fontWeight: 800, color: "#5C420C" }}>
                Recorded consent required
              </h2>
              <p style={{ margin: "3px 0 0", fontSize: 12, color: "#8A6A22", fontWeight: 600 }}>
                Minor or unknown DOB · parent contact
              </p>
            </div>
          </div>
          <div style={{ padding: "22px 24px 24px" }}>
            <p style={{ margin: 0, fontSize: 14, color: "#3A4654", lineHeight: 1.55 }}>
              <strong>{studentName}</strong> is a minor (or their date of birth isn't on file). Before logging a
              parent contact, confirm that consent to contact the parent or guardian is recorded in the student's
              file.
            </p>
            <label
              style={{
                marginTop: 18,
                display: "flex",
                alignItems: "flex-start",
                gap: 11,
                cursor: "pointer",
                padding: 13,
                border: `1.5px solid ${consentGiven ? "#0E7C86" : "#EBDCB4"}`,
                borderRadius: 11,
                background: consentGiven ? "#E3F1F2" : "#FDF9EE",
              }}
            >
              <input
                type="checkbox"
                checked={consentGiven}
                onChange={(e) => setConsentGiven(e.target.checked)}
                style={{ marginTop: 2, width: 17, height: 17, accentColor: "#0A656D", flex: "none" }}
              />
              <span style={{ fontSize: 13.5, color: "#16202C", fontWeight: 600, lineHeight: 1.45 }}>
                I confirm recorded consent from the parent/guardian is on file for this student.
              </span>
            </label>
            <div style={{ marginTop: 22, display: "flex", justifyContent: "space-between", gap: 10 }}>
              <button className="btn-secondary" onClick={() => setStep("form")}>
                ← Back
              </button>
              <button className="btn-primary" disabled={!consentGiven || submit.isPending} onClick={handlePrimary}>
                Confirm &amp; log
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(22,30,41,.42)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 20,
        zIndex: 50,
      }}
    >
      <div
        onClick={stop}
        style={{
          background: "#fff",
          borderRadius: 16,
          width: "100%",
          maxWidth: 480,
          boxShadow: "0 24px 60px rgba(20,30,45,.28)",
          maxHeight: "90vh",
          overflow: "auto",
        }}
      >
        <div style={{ padding: "22px 24px 0", display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800, letterSpacing: "-.01em" }}>Log intervention</h2>
            <p className="tnum" style={{ margin: "5px 0 0", fontSize: 13, color: "#8A95A2", fontWeight: 500 }}>
              For {studentName}
            </p>
          </div>
          <button onClick={onClose} aria-label="Close" style={{ width: 30, height: 30, borderRadius: 8, color: "#8A95A2", fontSize: 17 }}>
            ✕
          </button>
        </div>
        <div style={{ padding: "20px 24px 24px" }}>
          <label style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".05em", color: "#A2ACB8" }}>TYPE</label>
          <div style={{ marginTop: 9, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            {TYPES.map((t) => (
              <button
                key={t}
                onClick={() => setType(t)}
                style={
                  t === type
                    ? {
                        padding: "10px 12px",
                        borderRadius: 9,
                        border: "1.5px solid #0E7C86",
                        background: "#E3F1F2",
                        color: "#0A656D",
                        fontWeight: 700,
                        fontSize: 13,
                        textAlign: "left",
                      }
                    : {
                        padding: "10px 12px",
                        borderRadius: 9,
                        border: "1px solid #E1E7EC",
                        background: "#fff",
                        color: "#5A6573",
                        fontWeight: 600,
                        fontSize: 13,
                        textAlign: "left",
                      }
                }
              >
                {TYPE_LABEL[t]}
              </button>
            ))}
          </div>

          <label style={{ display: "block", marginTop: 18, fontSize: 11, fontWeight: 700, letterSpacing: ".05em", color: "#A2ACB8" }}>
            WHAT WILL YOU DO?
          </label>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={TITLE_HINT[type]}
            style={{
              marginTop: 9,
              width: "100%",
              border: "1px solid #DDE4E9",
              borderRadius: 9,
              padding: "11px 13px",
              fontSize: 14,
              color: "#16202C",
              background: "#FAFBFC",
            }}
          />

          <label style={{ display: "block", marginTop: 16, fontSize: 11, fontWeight: 700, letterSpacing: ".05em", color: "#A2ACB8" }}>
            NOTES (OPTIONAL)
          </label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            style={{
              marginTop: 9,
              width: "100%",
              border: "1px solid #DDE4E9",
              borderRadius: 9,
              padding: "11px 13px",
              fontSize: 14,
              color: "#16202C",
              background: "#FAFBFC",
              resize: "vertical",
            }}
          />

          {adultParentNote && (
            <div
              style={{
                marginTop: 14,
                display: "flex",
                gap: 9,
                alignItems: "flex-start",
                background: "#F4F7F9",
                borderRadius: 9,
                padding: "11px 13px",
                fontSize: 12.5,
                color: "#6B7686",
                lineHeight: 1.45,
              }}
            >
              <span style={{ color: "#0A656D", fontWeight: 800 }}>ℹ</span>
              <span>{firstName} is an adult — contacting a parent doesn't require recorded consent.</span>
            </div>
          )}
          {needsConsentForThisType && (
            <div
              style={{
                marginTop: 14,
                display: "flex",
                gap: 9,
                alignItems: "flex-start",
                background: "#FBF3DE",
                border: "1px solid #EBDCB4",
                borderRadius: 9,
                padding: "12px 14px",
                fontSize: 12.5,
                color: "#7A5A12",
                lineHeight: 1.45,
              }}
            >
              <span style={{ fontWeight: 800 }}>◆</span>
              <span>
                <strong>{firstName} is a minor.</strong> Contacting a parent or guardian needs recorded consent on
                file. You'll confirm this on the next step.
              </span>
            </div>
          )}

          {submit.isError && (
            <div style={{ marginTop: 14, fontSize: 13, color: "#B42318", fontWeight: 600 }}>
              Couldn't log the intervention. Please try again.
            </div>
          )}

          <div style={{ marginTop: 22, display: "flex", justifyContent: "flex-end", gap: 10 }}>
            <button className="btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button className="btn-primary" disabled={!title.trim() || submit.isPending} onClick={handlePrimary}>
              {needsConsentForThisType ? "Review consent →" : "Log intervention"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
