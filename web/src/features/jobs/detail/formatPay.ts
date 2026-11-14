import type { Pay } from "../../../api/types";

function formatAmount(amount: number, currency: string): string {
  const digits = Number.isInteger(amount) ? 0 : 2;
  return new Intl.NumberFormat("en", {
    style: "currency",
    currency,
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(amount);
}

export function formatPay(pay: Pay): string {
  if (pay.max === null) {
    // The API never sends both bounds null.
    const min = formatAmount(pay.min!, pay.currency);
    return `from ${min}/${pay.period}`;
  }
  if (pay.min === null) {
    const max = formatAmount(pay.max, pay.currency);
    return `up to ${max}/${pay.period}`;
  }
  const min = formatAmount(pay.min, pay.currency);
  if (pay.min === pay.max) return `${min}/${pay.period}`;
  const max = formatAmount(pay.max, pay.currency);
  return `${min} – ${max}/${pay.period}`;
}
