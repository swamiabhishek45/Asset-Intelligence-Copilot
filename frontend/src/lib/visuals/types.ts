export type FlytVisualType =
  | "status_card"
  | "table"
  | "text"
  | "line_chart"
  | "bar_chart"
  | "heatmap"
  | "map"
  | string;

export type CopilotVisualInput = {
  text: string;
  visual_type: FlytVisualType;
  visual_payload: Record<string, unknown>;
  citations?: string[];
};

export type LineChartPayload = {
  asset_id?: string;
  well_type?: string;
  threshold_c?: number;
  readings?: Array<{
    date: string;
    wellhead_temp_c: number;
    ambient_temp_c: number;
    delta_t?: number;
    producing?: boolean;
    inspection_id?: string;
  }>;
  non_producing_dates?: string[];
};

export type BarChartPayload = {
  categories?: string[];
  series?: Array<{ name: string; data: number[] }>;
};

export type TablePayload = {
  headers?: string[];
  rows?: unknown[][];
};

export type HeatmapPayload = {
  x_labels?: string[];
  y_labels?: string[];
  data?: number[][];
};

export type MapPayload = {
  pins?: Array<{
    title: string;
    lat: number;
    lon: number;
    volume?: number;
  }>;
};
