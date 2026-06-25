// Tracks the most recent import batch the signed-in user has seen *in this
// browser*, so the stale-data banner (Phase 3 guide §B.6) can be shown
// without a GET /imports list endpoint -- which doesn't exist and is out of
// scope for PART B (no new backend endpoints beyond PART A). Written by the
// Imports page after a create/refresh; read by the layout banner.

const KEY = "copilot.last_import";

export interface LastImportStatus {
  importBatchId: string;
  status: string;
  riskRecomputeStatus: string | null;
}

export function setLastImportStatus(value: LastImportStatus): void {
  sessionStorage.setItem(KEY, JSON.stringify(value));
}

export function getLastImportStatus(): LastImportStatus | null {
  const raw = sessionStorage.getItem(KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as LastImportStatus;
  } catch {
    return null;
  }
}
