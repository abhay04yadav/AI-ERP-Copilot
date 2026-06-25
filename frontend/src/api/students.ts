import { apiClient } from "./client";
import type { Student360Response } from "./types";

export async function getStudent360(studentId: string): Promise<Student360Response> {
  const { data } = await apiClient.get<Student360Response>(`/students/${studentId}`);
  return data;
}
