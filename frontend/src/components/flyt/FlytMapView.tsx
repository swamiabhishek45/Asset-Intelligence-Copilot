"use client";

type FlytMapViewProps = {
  titles: string[];
  lats: number[];
  lons: number[];
  volumes: number[];
};

function normalizePins(props: FlytMapViewProps) {
  const { titles, lats, lons, volumes } = props;
  const n = Math.min(titles.length, lats.length, lons.length);
  const pins = [];
  for (let i = 0; i < n; i += 1) {
    pins.push({
      title: titles[i] ?? `Pin ${i + 1}`,
      lat: lats[i] ?? 0,
      lon: lons[i] ?? 0,
      volume: volumes[i],
    });
  }
  return pins;
}

export function FlytMapView(props: FlytMapViewProps) {
  const pins = normalizePins(props);
  if (!pins.length) {
    return <p className="text-muted-foreground text-sm">No coordinates to plot.</p>;
  }

  const minLat = Math.min(...pins.map((p) => p.lat));
  const maxLat = Math.max(...pins.map((p) => p.lat));
  const minLon = Math.min(...pins.map((p) => p.lon));
  const maxLon = Math.max(...pins.map((p) => p.lon));
  const padLat = (maxLat - minLat || 0.01) * 0.15;
  const padLon = (maxLon - minLon || 0.01) * 0.15;
  const lat0 = minLat - padLat;
  const lat1 = maxLat + padLat;
  const lon0 = minLon - padLon;
  const lon1 = maxLon + padLon;

  const toX = (lon: number) => ((lon - lon0) / (lon1 - lon0)) * 100;
  const toY = (lat: number) => 100 - ((lat - lat0) / (lat1 - lat0)) * 100;

  return (
    <div className="flyt-map flex w-full flex-col gap-3">
      <div className="relative aspect-[16/9] w-full overflow-hidden rounded-md border border-border bg-muted">
        <svg viewBox="0 0 100 100" className="h-full w-full" role="img" aria-label="Well map">
          <rect x="0" y="0" width="100" height="100" fill="#fafafa" />
          {[20, 40, 60, 80].map((g) => (
            <g key={g} stroke="#e4e4e7" strokeWidth="0.15">
              <line x1={g} y1="0" x2={g} y2="100" />
              <line x1="0" y1={g} x2="100" y2={g} />
            </g>
          ))}
          {pins.map((pin) => (
            <g key={pin.title}>
              <circle
                cx={toX(pin.lon)}
                cy={toY(pin.lat)}
                r="2.2"
                fill="#0a0a0a"
                stroke="#fafafa"
                strokeWidth="0.4"
              />
              <title>
                {pin.title} ({pin.lat.toFixed(4)}, {pin.lon.toFixed(4)})
                {pin.volume !== undefined ? ` · ${pin.volume} bbl` : ""}
              </title>
            </g>
          ))}
        </svg>
      </div>
      <ul className="grid gap-1 text-sm">
        {pins.map((pin) => (
          <li key={pin.title} className="flex justify-between gap-4 border-b border-border/60 py-1">
            <span className="font-medium">{pin.title}</span>
            <span className="text-muted-foreground tabular-nums">
              {pin.lat.toFixed(4)}, {pin.lon.toFixed(4)}
              {pin.volume !== undefined ? ` · ${pin.volume} bbl` : ""}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
