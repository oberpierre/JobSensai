// The literal the contract reserves for "employment_type IS NULL" on the wire,
// shown to a reader as a word rather than the sentinel itself.
const UNSPECIFIED_EMPLOYMENT_TYPE = "__unspecified__";

export function facetValueLabel(value: string): string {
  return value === UNSPECIFIED_EMPLOYMENT_TYPE ? "Unspecified" : value;
}
