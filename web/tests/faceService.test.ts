import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { api } from "../lib/api";
import { enrollFace, getFaceStatus } from "../lib/faceService";

describe("faceService", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("enrollFace posts a FormData body with one entry per photo, no manual Content-Type", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      data: { photos_accepted: 2, photos_rejected: [], embedding_dimension: 512 },
    });
    const photos = [
      new File(["a"], "a.jpg", { type: "image/jpeg" }),
      new File(["b"], "b.jpg", { type: "image/jpeg" }),
    ];

    const result = await enrollFace("emp-1", photos);

    expect(api.post).toHaveBeenCalledTimes(1);
    const [url, body, config] = vi.mocked(api.post).mock.calls[0];
    expect(url).toBe("/face/enroll/emp-1");
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).getAll("photos")).toEqual(photos);
    // No explicit headers override — letting the browser set the multipart
    // boundary itself is load-bearing (see faceService.ts comment).
    expect(config).toBeUndefined();
    expect(result.photos_accepted).toBe(2);
  });

  it("getFaceStatus GETs the employee's status endpoint", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: { enrolled: true, enrolled_at: "2026-08-07T00:00:00Z", photo_count: 3 },
    });

    const status = await getFaceStatus("emp-1");

    expect(api.get).toHaveBeenCalledWith("/face/status/emp-1");
    expect(status.enrolled).toBe(true);
    expect(status.photo_count).toBe(3);
  });
});
