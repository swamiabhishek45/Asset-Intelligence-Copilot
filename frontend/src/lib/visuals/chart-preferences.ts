export type ChartPreference =
  | "auto"
  | "pie"
  | "donut"
  | "line"
  | "area"
  | "bar"
  | "horizontal_bar"
  | "scatter"
  | "radar"
  | "table";

export function detectChartPreference(query: string): ChartPreference {
  const q = query.toLowerCase();

  if (/\bpie\b|\bdonut\b|\bbreakdown\b|\bshare of\b/.test(q)) {
    return /\bdonut\b/.test(q) ? "donut" : "pie";
  }
  if (/\bscatter\b|\bcorrelation\b|\bvs\.?\b/.test(q)) return "scatter";
  if (/\bradar\b|\bspider\b/.test(q)) return "radar";
  if (/\bhorizontal bar\b|\branked list\b/.test(q)) return "horizontal_bar";
  if (/\barea chart\b|\bfilled\b|\bcumulative\b/.test(q)) return "area";
  if (/\bline chart\b|\bline graph\b|\bgraph\b|\btrend\b|\bover time\b|\btime series\b/.test(q)) {
    return "line";
  }
  if (/\bbar chart\b|\bcompare\b|\branking\b|\btop \d+\b/.test(q)) return "bar";
  if (/\btable\b|\blist\b|\brows\b/.test(q)) return "table";

  return "auto";
}

export function pieVariant(preference: ChartPreference): "pie" | "donut" {
  return preference === "donut" ? "donut" : "pie";
}
