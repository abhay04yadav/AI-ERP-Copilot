import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { getImportBatch } from "../api/imports";
import { recompute } from "../api/risk";
import { ErrorState } from "../design/States";
import { useToast } from "../design/ToastContext";
import { setLastImportStatus, getLastImportStatus } from "../layout/lastImportStatus";

const RECOMPUTE_OK_STATUSES = new Set(["ok"]);

export function ImportsPage() {
  const flashToast = useToast();
  const [batchId, setBatchId] = useState(getLastImportStatus()?.importBatchId ?? "");
  const [lookupId, setLookupId] = useState(batchId);

  const batchQuery = useQuery({
    queryKey: ["import-batch", lookupId],
    queryFn: () => getImportBatch(lookupId),
    enabled: !!lookupId,
  });

  const recomputeMutation = useMutation({
    mutationFn: () => recompute({ scope: "tenant" }),
    onSuccess: (summary) => {
      flashToast(`Recompute done — ${summary.changed} changed, ${summary.evaluated} evaluated`);
    },
  });

  useEffect(() => {
    if (batchQuery.data) {
      setLastImportStatus({
        importBatchId: batchQuery.data.id,
        status: batchQuery.data.status,
        riskRecomputeStatus: batchQuery.data.risk_recompute_status ?? null,
      });
    }
  }, [batchQuery.data]);

  const needsRecompute = batchQuery.data?.risk_recompute_status
    ? !RECOMPUTE_OK_STATUSES.has(batchQuery.data.risk_recompute_status)
    : false;

  return (
    <div className="main-pad" style={{ padding: "30px 36px 60px", maxWidth: 760, width: "100%" }}>
      <h1 style={{ margin: 0, fontSize: 25, fontWeight: 800, letterSpacing: "-.02em" }}>Imports</h1>
      <p style={{ margin: "6px 0 0", fontSize: 13.5, color: "#6B7686", fontWeight: 500 }}>
        Look up an import batch by id to check its load and risk-recompute status.
      </p>

      <div className="card" style={{ marginTop: 22, display: "flex", flexDirection: "column", gap: 14 }}>
        <label style={{ fontSize: 12, fontWeight: 700, color: "#5A6573" }}>
          Import batch id
          <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
            <input
              value={batchId}
              onChange={(e) => setBatchId(e.target.value)}
              placeholder="e.g. 9efd1c21-34ae-4946-a0a8-7f5fcedf8e47"
              style={{ flex: 1, border: "1px solid #DDE4E9", borderRadius: 9, padding: "9px 12px", fontSize: 14 }}
            />
            <button className="btn-primary" onClick={() => setLookupId(batchId)} disabled={!batchId}>
              Look up
            </button>
          </div>
        </label>

        {batchQuery.isError && (
          <ErrorState title="Batch not found" message="Check the id and try again." onRetry={() => batchQuery.refetch()} />
        )}

        {batchQuery.data && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <Row label="Pipeline status" value={batchQuery.data.status} />
            <Row label="Rows loaded" value={`${batchQuery.data.row_count_loaded} / ${batchQuery.data.row_count_raw}`} />
            <Row label="Rows quarantined" value={String(batchQuery.data.row_count_quarantined)} />
            <Row label="Risk recompute" value={batchQuery.data.risk_recompute_status ?? "—"} />
            {batchQuery.data.error && <Row label="Error" value={batchQuery.data.error} />}

            {needsRecompute && (
              <div
                style={{
                  marginTop: 8,
                  background: "#FBF3DE",
                  border: "1px solid #EBDCB4",
                  borderRadius: 9,
                  padding: "12px 14px",
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  flexWrap: "wrap",
                }}
              >
                <span style={{ fontSize: 12.5, color: "#7A5A12", fontWeight: 600 }}>
                  Risk scores may be out of date for this batch.
                </span>
                <button
                  className="btn-secondary"
                  style={{ marginLeft: "auto" }}
                  disabled={recomputeMutation.isPending}
                  onClick={() => recomputeMutation.mutate()}
                >
                  {recomputeMutation.isPending ? "Recomputing…" : "Re-run recompute"}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, borderBottom: "1px solid #F0F3F5", paddingBottom: 8 }}>
      <span style={{ color: "#8A95A2", fontWeight: 600 }}>{label}</span>
      <span style={{ color: "#16202C", fontWeight: 700 }}>{value}</span>
    </div>
  );
}
