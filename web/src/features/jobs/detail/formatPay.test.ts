import { describe, expect, it } from "vitest";
import { formatPay } from "./formatPay";

describe("formatPay", () => {
  it("formats a euro range", () => {
    expect(
      formatPay({ min: 155000, max: 205000, currency: "EUR", period: "year" }),
    ).toBe("€155,000 – €205,000/year");
  });

  it("formats a dollar range", () => {
    expect(
      formatPay({ min: 190000, max: 230000, currency: "USD", period: "year" }),
    ).toBe("$190,000 – $230,000/year");
  });

  it("shows pence for a single fractional amount", () => {
    expect(
      formatPay({ min: 25.5, max: 25.5, currency: "GBP", period: "hour" }),
    ).toBe("£25.50/hour");
  });

  it("shows a single whole amount without decimals", () => {
    expect(
      formatPay({ min: 25, max: 25, currency: "EUR", period: "hour" }),
    ).toBe("€25/hour");
  });

  it("says from for a floor only", () => {
    expect(
      formatPay({ min: 50000, max: null, currency: "EUR", period: "year" }),
    ).toBe("from €50,000/year");
  });

  it("says up to for a cap only", () => {
    expect(
      formatPay({ min: null, max: 80000, currency: "EUR", period: "year" }),
    ).toBe("up to €80,000/year");
  });
});
