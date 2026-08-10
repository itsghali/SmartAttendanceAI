import { api } from "./api";

export interface Employee {
  id: string;
  employee_code: string;
  department_id: string | null;
  job_title: string;
  status: string;
  user: {
    email: string;
    full_name: string;
  };
}

export async function listEmployees(): Promise<Employee[]> {
  const response = await api.get("/employees", { params: { limit: 200 } });
  return response.data.items;
}
