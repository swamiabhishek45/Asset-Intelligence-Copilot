import {
  detectChartPreference,
  pieVariant,
  type ChartPreference,
} from "@/lib/visuals/chart-preferences";
import {
  langNumberList,
  langNumberMatrix,
  langString,
  langStringList,
} from "@/lib/visuals/lang-format";
import type {
  BarChartPayload,
  CopilotVisualInput,
  HeatmapPayload,
  LineChartPayload,
  MapPayload,
  TablePayload,
} from "@/lib/visuals/types";

function asRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function citationsBlock(citations: string[] | undefined): string | null {
  if (!citations?.length) return null;
  return `vizCites = TagBlock(${langStringList(citations)}, "sm")`;
}

function narrativeBlock(text: string): string {
  return `vizNarrative = MarkDownRenderer(${langString(text)}, "clear")`;
}

function tableFromPayload(payload: TablePayload): string {
  const headers = payload.headers ?? [];
  const rows = payload.rows ?? [];
  if (!headers.length) {
    return `vizMain = TextContent(${langString("No tabular data returned.")}, "small")`;
  }
  const cols = headers.map((header, index) => {
    const column = rows.map((row) => {
      const cell = row[index];
      if (cell === null || cell === undefined) return "";
      if (typeof cell === "number") return cell;
      const asNum = Number(cell);
      return Number.isFinite(asNum) && String(cell).trim() !== "" ? asNum : String(cell);
    });
    const numeric = column.every((v) => typeof v === "number");
    const dataExpr = numeric ? langNumberList(column as number[]) : langStringList(column as string[]);
    const typeArg = numeric ? ', "number"' : "";
    return `Col(${langString(header)}, ${dataExpr}${typeArg})`;
  });
  return `vizMain = Table([${cols.join(", ")}])`;
}

function barChartFromPayload(payload: BarChartPayload, preference: ChartPreference): string {
  const categories = payload.categories ?? [];
  const series = payload.series ?? [];
  const values = series[0]?.data ?? [];
  const name = series[0]?.name ?? "Value";

  if (
    categories.length &&
    values.length === categories.length &&
    (preference === "pie" || preference === "donut")
  ) {
    const variant = pieVariant(preference);
    return `vizMain = PieChart(${langStringList(categories)}, ${langNumberList(values)}, ${langString(variant)})`;
  }

  if (preference === "horizontal_bar" && categories.length && series.length) {
    const seriesExpr = series
      .map((s) => `Series(${langString(s.name)}, ${langNumberList(s.data)})`)
      .join(", ");
    return `vizMain = HorizontalBarChart(${langStringList(categories)}, [${seriesExpr}], "grouped", ${langString(name)}, ${langString("Category")})`;
  }

  if (categories.length && series.length) {
    const seriesExpr = series
      .map((s) => `Series(${langString(s.name)}, ${langNumberList(s.data)})`)
      .join(", ");
    return `vizMain = BarChart(${langStringList(categories)}, [${seriesExpr}], "grouped", ${langString("Category")}, ${langString(name)}, 320)`;
  }

  return tableFromPayload({ headers: ["Category", name], rows: categories.map((c, i) => [c, values[i]]) });
}

function lineChartFromPayload(payload: LineChartPayload, preference: ChartPreference): string {
  const readings = payload.readings ?? [];
  if (!readings.length) {
    return `vizMain = TextContent(${langString("No time-series readings in the response.")}, "small")`;
  }

  const labels = readings.map((r) => r.date);
  const wellhead = readings.map((r) => r.wellhead_temp_c);
  const ambient = readings.map((r) => r.ambient_temp_c);
  const seriesExpr = `[Series(${langString("Wellhead °C")}, ${langNumberList(wellhead)}), Series(${langString("Ambient °C")}, ${langNumberList(ambient)})]`;
  const variant = preference === "area" ? "natural" : "natural";
  const chartName = preference === "area" ? "AreaChart" : "LineChart";

  const nonProd = payload.non_producing_dates?.length
    ? `vizNote = Callout("warning", ${langString("Non-producing weeks")}, ${langString(`Marked non-producing: ${payload.non_producing_dates.join(", ")}`)})`
    : null;

  const main = `vizMain = ${chartName}(${langStringList(labels)}, ${seriesExpr}, ${langString(variant)}, ${langString("Week")}, ${langString("Temperature (°C)")}, 320)`;
  return nonProd ? `${main}\n${nonProd}` : main;
}

function statusCardFromPayload(payload: Record<string, unknown>): string {
  const latest = asRecord(payload.latest_inspection);
  const assetId =
    typeof payload.asset_id === "string"
      ? payload.asset_id
      : typeof latest.asset_id === "string"
        ? latest.asset_id
        : "Well";

  const producing =
    typeof payload.producing_oil === "boolean" ? payload.producing_oil : undefined;
  const statusLabel =
    producing === undefined
      ? "Status"
      : producing
        ? "Producing oil"
        : "Not producing";

  const delta =
    latest.temp_delta_c !== undefined
      ? `${latest.temp_delta_c} °C ΔT`
      : payload.downtime_days !== undefined
        ? `${payload.downtime_days} days down`
        : "—";

  const inspectionLine =
    latest.inspection_id && latest.inspected_at
      ? `${latest.inspection_id} · ${String(latest.inspected_at).slice(0, 10)}`
      : "Latest inspection";

  return [
    `vizMain = OverviewCardBlock([statusA, statusB], "grid", true)`,
    `statusA = OverviewCardItem("production", statusATop, statusAMetric)`,
    `statusATop = Text("text", ${langString(statusLabel)}, ${langString(assetId)}, "text", "md")`,
    `statusAMetric = MetricIndicatorInline(${langString(String(delta))}, ${langString("Thermal / downtime")})`,
    `statusB = OverviewCardItem("inspection", statusBTop, statusBMetric)`,
    `statusBTop = Text("text", ${langString("Inspection")}, ${langString("Latest")}, "text", "md")`,
    `statusBMetric = MetricIndicatorInline(${langString(inspectionLine)}, ${langString(
      latest.inspector_name ? String(latest.inspector_name) : "Field record",
    )})`,
  ].join("\n");
}

function heatmapFromPayload(payload: HeatmapPayload): string {
  const xLabels = payload.x_labels ?? [];
  const yLabels = payload.y_labels ?? [];
  const cells = payload.data ?? [];
  if (!xLabels.length || !yLabels.length || !cells.length) {
    return `vizMain = TextContent(${langString("Heatmap data was empty.")}, "small")`;
  }
  return `vizMain = FlytHeatmap(${langStringList(xLabels)}, ${langStringList(yLabels)}, ${langNumberMatrix(cells)})`;
}

function mapFromPayload(payload: MapPayload): string {
  const pins = payload.pins ?? [];
  if (!pins.length) {
    return `vizMain = TextContent(${langString("No map pins returned.")}, "small")`;
  }
  const titles = pins.map((p) => p.title);
  const lats = pins.map((p) => p.lat);
  const lons = pins.map((p) => p.lon);
  const volumes = pins.map((p) => (p.volume !== undefined ? p.volume : 0));
  return `vizMain = FlytMap(${langStringList(titles)}, ${langNumberList(lats)}, ${langNumberList(lons)}, ${langNumberList(volumes)})`;
}

function resolveVisualMain(
  visualType: string,
  payload: Record<string, unknown>,
  preference: ChartPreference,
): { mainLines: string; title: string; subtitle: string } {
  switch (visualType) {
    case "line_chart":
      return {
        mainLines: lineChartFromPayload(payload as LineChartPayload, preference),
        title: "Temperature trend",
        subtitle: typeof payload.asset_id === "string" ? payload.asset_id : "Weekly readings",
      };
    case "bar_chart":
      return {
        mainLines: barChartFromPayload(payload as BarChartPayload, preference),
        title: preference === "pie" || preference === "donut" ? "Share breakdown" : "Comparison chart",
        subtitle: "Rankings from backend data",
      };
    case "table":
      return {
        mainLines: tableFromPayload(payload as TablePayload),
        title: "Data table",
        subtitle: "Structured backend rows",
      };
    case "heatmap":
      return {
        mainLines: heatmapFromPayload(payload as HeatmapPayload),
        title: "Spill heatmap",
        subtitle: "Area × month intensity",
      };
    case "map":
      return {
        mainLines: mapFromPayload(payload as MapPayload),
        title: "Field map",
        subtitle: "Well locations from backend pins",
      };
    case "status_card":
      return {
        mainLines: statusCardFromPayload(payload),
        title: "Well status",
        subtitle: "Production and inspection snapshot",
      };
    case "text":
    default:
      return {
        mainLines: `vizMain = Separator("horizontal")`,
        title: "Asset intelligence",
        subtitle: "FlytBase copilot",
      };
  }
}

/** Build a complete OpenUI Lang program for a copilot tool result. */
export function buildCopilotVisualProgram(
  result: CopilotVisualInput,
  userQuery: string,
): string | null {
  const payload = result.visual_payload ?? {};
  const hasPayload = Object.keys(payload).length > 0;
  const preference = detectChartPreference(userQuery);

  if (result.visual_type === "text" && !hasPayload) {
    return null;
  }

  const { mainLines, title, subtitle } = resolveVisualMain(
    result.visual_type,
    payload,
    preference,
  );

  const citeLine = citationsBlock(result.citations);
  const cardChildren = ["vizHeader", "vizMain"];
  if (mainLines.includes("vizNote =")) cardChildren.push("vizNote");
  cardChildren.push("vizNarrative");
  if (citeLine) {
    cardChildren.push("vizCites");
  }

  const lines = [
    `root = Card([${cardChildren.join(", ")}], "card", "column", "m")`,
    `vizHeader = CardHeader(${langString(title)}, ${langString(subtitle)})`,
    mainLines,
    narrativeBlock(result.text),
  ];
  if (citeLine) lines.push(citeLine);

  return lines.join("\n");
}

export function buildVisualPromptAppendix(sampleProgram: string | null): string {
  if (!sampleProgram) return "";
  return [
    "Reference layout (adapt titles only; keep data bindings from the tool):",
    sampleProgram,
  ].join("\n");
}
