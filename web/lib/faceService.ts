import { api } from "./api";

export interface FaceEnrollRejectedPhoto {
  index: number;
  reason: string;
}

export interface FaceEnrollResult {
  photos_accepted: number;
  photos_rejected: FaceEnrollRejectedPhoto[];
  embedding_dimension: number;
}

export interface FaceStatus {
  enrolled: boolean;
  enrolled_at: string | null;
  photo_count: number;
}

export async function enrollFace(employeeId: string, photos: File[]): Promise<FaceEnrollResult> {
  const form = new FormData();
  for (const photo of photos) {
    form.append("photos", photo);
  }
  // No explicit Content-Type here — the browser must set it itself when
  // given a FormData body, since it needs to generate the multipart
  // boundary. Setting "multipart/form-data" manually (no boundary) breaks
  // parsing server-side.
  const response = await api.post<FaceEnrollResult>(`/face/enroll/${employeeId}`, form);
  return response.data;
}

export async function getFaceStatus(employeeId: string): Promise<FaceStatus> {
  const response = await api.get<FaceStatus>(`/face/status/${employeeId}`);
  return response.data;
}
