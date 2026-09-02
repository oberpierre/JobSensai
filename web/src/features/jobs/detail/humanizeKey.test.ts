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

  it("stringifies a value that is neither a string nor an array", () => {
    expect(metadataValueText({ min: 100, max: 120 })).toBe(
      '{"min":100,"max":120}',
    );
  });
});
