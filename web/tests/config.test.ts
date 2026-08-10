import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { apiUrl, getApiBaseUrl } from "../lib/config";

describe("config", () => {
  const original = process.env.NEXT_PUBLIC_API_BASE_URL;

  beforeEach(() => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000/";
  });

  afterEach(() => {
    process.env.NEXT_PUBLIC_API_BASE_URL = original;
  });

  it("strips trailing slashes from the base url", () => {
    expect(getApiBaseUrl()).toBe("http://localhost:8000");
  });

  it("joins base url and path cleanly", () => {
    expect(apiUrl("/health")).toBe("http://localhost:8000/health");
  });

  it("throws when the base url is not configured", () => {
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    expect(() => getApiBaseUrl()).toThrow();
  });
});
