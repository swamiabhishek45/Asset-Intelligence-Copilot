"use client";

import { useEffect, useState } from "react";

type Health = {
  status: string;
  wells_loaded: number;
  benchmark_today: string;
};

export function BackendStatus() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const res = await fetch("/api/backend/health");
        if (!res.ok) throw new Error(`${res.status}`);
        const data = (await res.json()) as Health;
        if (!cancelled) {
          setHealth(data);
          setError(null);
        }
      } catch {
        if (!cancelled) {
          setHealth(null);
          setError("offline");
        }
      }
    }

    void load();
    const id = window.setInterval(load, 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  return (
    <div className="flytbase-sidebar-status w-full min-w-0 border-t border-border pt-3">
      <p className="text-muted-foreground mb-2 text-[10px] font-medium uppercase tracking-wider">
        Backend API
      </p>
      {health ? (
        <dl className="space-y-1 text-xs">
          <div className="flex items-center justify-between gap-2">
            <dt className="text-muted-foreground">Status</dt>
            <dd className="font-medium">healthy</dd>
          </div>
          <div className="flex items-center justify-between gap-2">
            <dt className="text-muted-foreground">Wells</dt>
            <dd className="tabular-nums">{health.wells_loaded}</dd>
          </div>
          <div className="flex items-center justify-between gap-2">
            <dt className="text-muted-foreground">Benchmark</dt>
            <dd className="tabular-nums">{health.benchmark_today}</dd>
          </div>
        </dl>
      ) : (
        <div className="space-y-1 text-xs">
          <p className="font-medium capitalize">{error ?? "checking…"}</p>
          <p className="text-muted-foreground leading-snug">Run FastAPI on port 8000 (see docs).</p>
        </div>
      )}
    </div>
  );
}
