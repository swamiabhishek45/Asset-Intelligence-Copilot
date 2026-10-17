export const FLYT_VISUAL_RULES = [
  "After query_asset_copilot returns, ALWAYS render structured UI — never answer with markdown alone when visual_payload is non-empty.",
  "When the tool result includes openui_visual, emit those OpenUI Lang statements verbatim as your program (same variable names: root, vizHeader, vizMain, vizNarrative, vizCites). You may add Callout only for backend warnings.",
  "Match user chart intent: pie/donut → PieChart; trend/graph → LineChart or AreaChart; compare/ranking → BarChart; table/list → Table; map → FlytMap; heatmap → FlytHeatmap.",
  "Use FlytHeatmap(xLabels, yLabels, cells) for backend visual_type heatmap. Use FlytMap(titles, lats, lons, volumes) for visual_type map.",
  "Keep FlytBase styling: monochrome cards, TagBlock for citations, MarkDownRenderer for narrative text from tool result.",
  "Do not invent numeric series — only use values from visual_payload and text from the tool.",
];
