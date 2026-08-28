// A minute/hour/day approximation, matching the "2h ago" / "11d ago" style the
// design uses, because nothing here needs calendar precision.
export function relativeTime(iso: string): string {
  const diffMinutes = Math.round(
    (Date.now() - new Date(iso).getTime()) / 60000,
  );
  if (diffMinutes < 60) return `${Math.max(diffMinutes, 0)}m ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.round(diffHours / 24);
  return `${diffDays}d ago`;
}
