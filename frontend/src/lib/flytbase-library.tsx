"use client";

import { FlytHeatmapView } from "@/components/flyt/FlytHeatmapView";
import { FlytMapView } from "@/components/flyt/FlytMapView";
import { FLYT_VISUAL_RULES } from "@/lib/visuals/visual-rules";
import { defineComponent } from "@openuidev/react-lang";
import {
  openuiAdditionalRules,
  openuiLibrary,
  openuiPromptOptions,
} from "@openuidev/react-ui/genui-lib";
import { z } from "zod";

const FlytHeatmapSchema = z.object({
  xLabels: z.array(z.string()),
  yLabels: z.array(z.string()),
  cells: z.array(z.array(z.number())),
});

export const FlytHeatmap = defineComponent({
  name: "FlytHeatmap",
  props: FlytHeatmapSchema,
  description:
    "Monochrome matrix heatmap for area×month or category grids. Pass column labels, row labels, and a numeric matrix (rows align with yLabels).",
  component: ({ props }) => (
    <FlytHeatmapView
      xLabels={props.xLabels as string[]}
      yLabels={props.yLabels as string[]}
      cells={props.cells as number[][]}
    />
  ),
});

const FlytMapSchema = z.object({
  titles: z.array(z.string()),
  lats: z.array(z.number()),
  lons: z.array(z.number()),
  volumes: z.array(z.number()).optional(),
});

export const FlytMap = defineComponent({
  name: "FlytMap",
  props: FlytMapSchema,
  description:
    "Field map from parallel arrays: well titles, latitudes, longitudes, and optional spill volumes (bbl). Renders SVG plot plus coordinate list.",
  component: ({ props }) => (
    <FlytMapView
      titles={props.titles as string[]}
      lats={props.lats as number[]}
      lons={props.lons as number[]}
      volumes={(props.volumes as number[] | undefined) ?? []}
    />
  ),
});

export const flytbaseLibrary = openuiLibrary.extend({
  components: {
    add: [
      { component: FlytHeatmap, slots: ["Card.children", "TabItem.content"] },
      { component: FlytMap, slots: ["Card.children", "TabItem.content"] },
    ],
  },
});

export const flytbasePromptOptions = {
  examples: openuiPromptOptions.examples,
  additionalRules: [...openuiAdditionalRules, ...FLYT_VISUAL_RULES],
};
