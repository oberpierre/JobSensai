import { describe, expect, it } from "vitest";

// Proves //web:vitest_test genuinely executes tests. S4 deletes this file.
describe("smoke", () => {
  it("runs", () => {
    expect(1 + 1).toBe(2);
  });
});
