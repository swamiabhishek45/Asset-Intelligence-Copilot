"use client";

type FlytHeatmapViewProps = {
  xLabels: string[];
  yLabels: string[];
  cells: number[][];
};

function cellColor(value: number, max: number): string {
  if (max <= 0) return "#f4f4f5";
  const t = Math.min(1, value / max);
  const gray = Math.round(250 - t * 200);
  return `rgb(${gray}, ${gray}, ${gray})`;
}

export function FlytHeatmapView({ xLabels, yLabels, cells }: FlytHeatmapViewProps) {
  const flat = cells.flat();
  const max = flat.length ? Math.max(...flat, 1) : 1;

  return (
    <div className="flyt-heatmap w-full overflow-x-auto">
      <div
        className="inline-grid gap-px border border-border bg-border text-[11px]"
        style={{
          gridTemplateColumns: `minmax(7rem, auto) repeat(${xLabels.length}, minmax(2.25rem, 1fr))`,
        }}
      >
        <div className="bg-muted px-2 py-1.5 font-medium text-muted-foreground" />
        {xLabels.map((label) => (
          <div
            key={label}
            className="bg-muted px-1 py-1.5 text-center font-medium text-muted-foreground"
          >
            {label}
          </div>
        ))}
        {yLabels.map((rowLabel, rowIndex) => {
          const row = cells[rowIndex] ?? [];
          return (
            <div key={rowLabel} className="contents">
              <div className="bg-muted px-2 py-2 font-medium text-foreground">{rowLabel}</div>
              {xLabels.map((colLabel, colIndex) => {
                const value = row[colIndex] ?? 0;
                return (
                  <div
                    key={`${rowLabel}-${colLabel}`}
                    className="flex min-h-[2rem] items-center justify-center bg-background px-1 py-1 tabular-nums text-foreground"
                    style={{ backgroundColor: cellColor(value, max) }}
                    title={`${rowLabel} · ${colLabel}: ${value}`}
                  >
                    {value}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
