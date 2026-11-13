// metadata is schemaless, so a key nobody has curated a label for still reads as
// a sentence rather than a snake_case identifier.
export function humanizeKey(key: string): string {
  const spaced = key.replace(/_/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function scalarText(value: unknown): string | null {
  if (typeof value === "string" && value !== "") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

export function metadataValueText(value: unknown): string | null {
  if (Array.isArray(value)) {
    if (value.length === 0) return null;
    const texts = value.map(scalarText);
    return texts.every((text) => text !== null) ? texts.join(", ") : null;
  }
  return scalarText(value);
}
