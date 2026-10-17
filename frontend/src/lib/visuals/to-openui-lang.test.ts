import assert from "node:assert/strict";
import test from "node:test";

import { buildCopilotVisualProgram } from "./to-openui-lang";

test("bar_chart maps to BarChart program", () => {
  const program = buildCopilotVisualProgram(
    {
      text: "Top wells",
      visual_type: "bar_chart",
      visual_payload: {
        categories: ["WELL-0121", "WELL-0138"],
        series: [{ name: "Downtime Days", data: [49, 42] }],
      },
      citations: ["OM-T200"],
    },
    "Show a bar chart of downtime",
  );

  assert.ok(program);
  assert.match(program!, /BarChart\(/);
  assert.match(program!, /WELL-0121/);
  assert.match(program!, /TagBlock\(\["OM-T200"\]/);
});

test("user pie intent maps bar payload to PieChart", () => {
  const program = buildCopilotVisualProgram(
    {
      text: "Breakdown",
      visual_type: "bar_chart",
      visual_payload: {
        categories: ["A", "B", "C"],
        series: [{ name: "Share", data: [10, 20, 70] }],
      },
      citations: [],
    },
    "Show me a pie chart breakdown",
  );

  assert.ok(program);
  assert.match(program!, /PieChart\(/);
});

test("line_chart includes dual series", () => {
  const program = buildCopilotVisualProgram(
    {
      text: "Series",
      visual_type: "line_chart",
      visual_payload: {
        asset_id: "WELL-0001",
        readings: [
          { date: "2026-08-01", wellhead_temp_c: 50, ambient_temp_c: 40 },
          { date: "2026-08-08", wellhead_temp_c: 52, ambient_temp_c: 41 },
        ],
        non_producing_dates: ["2026-08-08"],
      },
      citations: [],
    },
    "line graph over time",
  );

  assert.ok(program);
  assert.match(program!, /LineChart\(/);
  assert.match(program!, /Wellhead/);
  assert.match(program!, /Non-producing weeks/);
});

test("heatmap uses FlytHeatmap component", () => {
  const program = buildCopilotVisualProgram(
    {
      text: "Heatmap",
      visual_type: "heatmap",
      visual_payload: {
        x_labels: ["Jan", "Feb"],
        y_labels: ["Area A"],
        data: [[1, 2]],
      },
      citations: [],
    },
    "heatmap please",
  );

  assert.ok(program);
  assert.match(program!, /FlytHeatmap\(/);
});
