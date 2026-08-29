// metadata is schemaless, so a key nobody has curated a label for still reads as
// a sentence rather than a snake_case identifier.
export function humanizeKey(key: string): string {
  const spaced = key.replace(/_/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function metadataValueText(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}
