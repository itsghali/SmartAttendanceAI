import { api } from "./api";

export interface Employee {
  id: string;
  employee_code: string;
  department_id: string | null;
  supervisor_id: string | null;
  job_title: string;
  phone_number: string;
  hire_date: string;
  status: string;
  user: {
    email: string;
    full_name: string;
    role: string;
  };
}

export interface EmployeeUpdate {
  department_id?: string | null;
  supervisor_id?: string | null;
  job_title?: string;
  phone_number?: string;
}

export interface EmployeeCreate {
  email: string;
  full_name: string;
  password: string;
  role_name: string;
  department_id: string | null;
  supervisor_id: string | null;
  job_title: string;
  phone_number: string;
  hire_date: string;
}

export type EmployeeStatus = "active" | "on_leave" | "terminated";

export async function listEmployees(): Promise<Employee[]> {
  const response = await api.get("/employees", { params: { limit: 200 } });
  return response.data.items;
}

export async function createEmployee(payload: EmployeeCreate): Promise<Employee> {
  const response = await api.post("/employees", payload);
  return response.data;
}

export async function updateEmployee(id: string, updates: EmployeeUpdate): Promise<Employee> {
  const response = await api.patch(`/employees/${id}`, updates);
  return response.data;
}

export async function updateEmployeeStatus(
  id: string,
  status: EmployeeStatus,
): Promise<Employee> {
  const response = await api.patch(`/employees/${id}/status`, { status });
  return response.data;
}
