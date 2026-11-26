"use client";

import { useEffect, useRef, useState } from "react";
import { recheckVersion, useApi, useWrite } from "@/lib/query";
import { useFilters, useSetParam, windowOptions } from "@/lib/filters";
import { ago } from "@/lib/format";
import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { DateInput } from "@astryxdesign/core/DateInput";
import { HStack } from "@astryxdesign/core/HStack";
import { Selector } from "@astryxdesign/core/Selector";
import { Tooltip } from "@astryxdesign/core/Tooltip";
import { VStack } from "@astryxdesign/core/VStack";

type Source = { connector: string; failed?: boolean; age_minutes: number | null; last_run: string | null; error?: string | null };
type SourcesData = {
  sources: Source[];
  configured: string[];
  waiting: string[];
  refresh_after_minutes: number;
  refresh: { running: boolean };
};
type Team = { team_id: string; name: string };

const RANK = { fresh: 0, stale: 1, failed: 2 } as const;
type Kind = keyof typeof RANK;

export function Header() {
  const filters = useFilters();
  const setParam = useSetParam();
  const write = useWrite();
  const teams = useApi("/api/teams");
  const sources = useApi("/api/sources");
  const [toast, setToast] = useState<string | null>(null);
  const posted = useRef(false);
  const wasRunning = useRef(false);

  const teamList = ((teams.data as { teams?: Team[] } | undefined)?.teams) ?? [];
  const data = sources.data as SourcesData | undefined;
  const running = Boolean(data?.refresh?.running);
  const refetch = sources.refetch;

  const refresh = async (body: unknown) => {
    try {
      await write("/api/refresh", "POST", body);
      await refetch?.();
    } catch (e) {
      setToast("Refresh failed: " + (e instanceof Error ? e.message : String(e)));
    }
  };

  useEffect(() => {
    if (posted.current) return;
    posted.current = true;
    void refresh({ only_stale: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => void refetch?.(), 3000);
    return () => clearInterval(timer);
  }, [running, refetch]);

  useEffect(() => {
    if (wasRunning.current && !running) void recheckVersion();
    wasRunning.current = running;
  }, [running]);

  const options = windowOptions(new Date());
  const worst: Record<string, { kind: Kind; last: string | null; error: string | null }> = {};
  for (const s of data?.sources ?? []) {
    const kind: Kind = s.failed ? "failed" : s.age_minutes === null || s.age_minutes >= (data?.refresh_after_minutes ?? 0) ? "stale" : "fresh";
    const cur = worst[s.connector];
    if (!cur || RANK[kind] > RANK[cur.kind]) worst[s.connector] = { kind, last: s.last_run, error: s.error ?? null };
  }

  const teamOptions = [{ value: "", label: "All repositories" }, ...teamList.map((t) => ({ value: t.team_id, label: t.name }))];
  const windowChoices = options.map(([value, label]) => ({ value, label }));
  const variants = { fresh: "success", stale: "warning", failed: "error" } as const;

  return (
    <VStack as="header" gap={2}>
      <HStack gap={2} align="end" wrap="wrap">
        <Selector label="Team" options={teamOptions} value={filters.team ?? ""} onChange={(v) => setParam("team", v)} />
        <Selector label="Window" options={windowChoices} value={filters.window ?? ""} onChange={(v) => setParam("window", v)} />
        {filters.window === "custom" && (
          <>
            <DateInput label="From" value={(filters.from || undefined) as never} onChange={(v) => setParam("from", v ?? "")} />
            <DateInput label="To" value={(filters.to || undefined) as never} onChange={(v) => setParam("to", v ?? "")} />
          </>
        )}
        <Button label="Refresh" onClick={() => void refresh({})} />
      </HStack>
      <HStack gap={1} wrap="wrap" aria-live="polite">
        {(data?.configured ?? []).map((name) => {
          const w = worst[name] ?? { kind: "stale" as Kind, last: null, error: null };
          const text = name + (w.kind === "failed" ? " failed" : " synced " + ago(w.last));
          const badge = <Badge variant={variants[w.kind]} label={text} data-kind={w.kind} data-error={w.error ?? undefined} />;
          return w.error ? <Tooltip key={name} content={w.error}>{badge}</Tooltip> : <span key={name}>{badge}</span>;
        })}
        {(data?.waiting ?? []).map((name) => (
          <Badge key={name} variant="neutral" label={name.replace("_", " ") + " not connected"} data-kind="waiting" />
        ))}
        {running && <Badge variant="info" label="refreshing" data-kind="refreshing" />}
      </HStack>
      {toast && <Banner status="error" title={toast} isDismissable onDismiss={() => setToast(null)} />}
    </VStack>
  );
}
