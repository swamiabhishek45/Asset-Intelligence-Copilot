/** Escape a value as an OpenUI Lang string literal. */
export function langString(value: string): string {
  return JSON.stringify(value);
}

export function langNumber(value: number): string {
  if (!Number.isFinite(value)) return "0";
  return String(value);
}

export function langStringList(values: string[]): string {
  return `[${values.map(langString).join(", ")}]`;
}

export function langNumberList(values: number[]): string {
  return `[${values.map(langNumber).join(", ")}]`;
}

export function langNumberMatrix(rows: number[][]): string {
  return `[${rows.map((row) => langNumberList(row)).join(", ")}]`;
}
