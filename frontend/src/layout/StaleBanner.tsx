import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { getLastImportStatus } from "./lastImportStatus";

export function StaleBanner() {
  const navigate = useNavigate();
  const [status, setStatus] = useState(() => getLastImportStatus());

  // Re-check when the tab regains focus (e.g. coming back from the Imports
  // page after a re-run) -- sessionStorage doesn't have a change event.
  useEffect(() => {
    function refresh() {
      setStatus(getLastImportStatus());
    }
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, []);

  if (!status || !status.riskRecomputeStatus || !["partial", "failed"].includes(status.riskRecomputeStatus)) {
    return null;
  }

  return (
    <div
      style={{
        background: "#FBF3DE",
        borderBottom: "1px solid #EBDCB4",
        padding: "10px 32px",
        display: "flex",
        alignItems: "center",
        gap: 10,
        fontSize: 13,
        color: "#7A5A12",
      }}
    >
      <span
        style={{
          width: 18,
          height: 18,
          borderRadius: "50%",
          background: "#E2BE5E",
          color: "#5C420C",
          fontWeight: 800,
          fontSize: 12,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flex: "none",
        }}
      >
        !
      </span>
      <span style={{ fontWeight: 600 }}>Risk scores may be out of date.</span>
      <span style={{ color: "#9A7A30" }}>
        The last import finished {status.riskRecomputeStatus === "failed" ? "without recomputing risk" : "partially"}.
      </span>
      <button
        onClick={() => navigate("/imports")}
        style={{ marginLeft: "auto", fontWeight: 700, fontSize: 12.5, color: "#7A5A12", textDecoration: "underline" }}
      >
        Go to imports
      </button>
    </div>
  );
}
