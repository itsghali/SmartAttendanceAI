import { api } from "./api";

export interface Department {
  id: string;
  name: string;
}

export async function listDepartments(): Promise<Department[]> {
  const response = await api.get("/departments");
  return response.data;
}
