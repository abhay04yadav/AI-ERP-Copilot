import { apiClient } from "./client";
import type { ImportBatchResponse } from "./types";

// There is no GET /imports list endpoint (only GET /imports/{id}) -- backend
// changes for Phase 3 were scoped to PART A's two summary endpoints + CORS,
// per the guide's rule #4 ("no new backend runtime deps... limited to PART A
// + the seed script"). The Imports screen therefore only tracks batches the
// signed-in user creates/views in the current session, not a historical list.
export async function getImportBatch(importBatchId: string): Promise<ImportBatchResponse> {
  const { data } = await apiClient.get<ImportBatchResponse>(`/imports/${importBatchId}`);
  return data;
}
