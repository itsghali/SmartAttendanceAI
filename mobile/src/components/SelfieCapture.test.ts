import { stripDataUrlPrefix } from "./SelfieCapture";

describe("stripDataUrlPrefix", () => {
  it("strips a web data-URL prefix, leaving only the raw base64 payload", () => {
    // What expo-camera's web implementation actually returns from
    // takePictureAsync({base64:true}) — canvas.toDataURL() output.
    const webPhotoBase64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAUA";
    expect(stripDataUrlPrefix(webPhotoBase64)).toBe("iVBORw0KGgoAAAANSUhEUgAAAAUA");
  });

  it("strips a jpeg data-URL prefix too, not just png", () => {
    const webPhotoBase64 = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD";
    expect(stripDataUrlPrefix(webPhotoBase64)).toBe("/9j/4AAQSkZJRgABAQAAAQABAAD");
  });

  it("is a no-op on native's raw base64 (no prefix present)", () => {
    // What takePictureAsync({base64:true}) returns on iOS/Android — no
    // "data:...," prefix at all. Must pass through unchanged.
    const nativePhotoBase64 = "iVBORw0KGgoAAAANSUhEUgAAAAUA";
    expect(stripDataUrlPrefix(nativePhotoBase64)).toBe(nativePhotoBase64);
  });

  it("does not corrupt a value that merely starts with 'data:' but has no comma", () => {
    const malformed = "data:notarealprefix";
    expect(stripDataUrlPrefix(malformed)).toBe(malformed);
  });
});
