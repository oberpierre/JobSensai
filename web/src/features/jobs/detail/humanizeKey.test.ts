import { describe, expect, it } from "vitest";
import { humanizeKey, metadataValueText } from "./humanizeKey";

describe("humanizeKey", () => {
  it("turns a snake_case key into a capitalized sentence fragment", () => {
    expect(humanizeKey("experience_level")).toBe("Experience level");
  });
});

describe("metadataValueText", () => {
  it("passes a string value through unchanged", () => {
    expect(metadataValueText("Mid")).toBe("Mid");
  });

  it("joins an array value with a comma, as artboard 1c draws Tags", () => {
    expect(metadataValueText(["Remote", "Hybrid"])).toBe("Remote, Hybrid");
  });

  it("renders a number as its text", () => {
    expect(metadataValueText(3)).toBe("3");
  });

  it("joins a list of strings and numbers", () => {
    expect(metadataValueText(["Mid", 2])).toBe("Mid, 2");
  });

  it("renders no empty string", () => {
    expect(metadataValueText("")).toBeNull();
  });

  it("renders no empty list", () => {
    expect(metadataValueText([])).toBeNull();
  });

  it("renders no boolean", () => {
    expect(metadataValueText(true)).toBeNull();
  });

  it("renders no object", () => {
    expect(metadataValueText({ min: 100, max: 120 })).toBeNull();
  });

  it("renders no list holding an object", () => {
    expect(metadataValueText([{ min_cents: 19000000 }])).toBeNull();
  });

  it("renders no list holding an empty string", () => {
    expect(metadataValueText(["", "Mid"])).toBeNull();
  });
});
