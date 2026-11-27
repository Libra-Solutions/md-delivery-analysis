"use client";

import { useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Heading } from "@astryxdesign/core/Heading";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Table } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useApi, useWrite, recheckVersion } from "@/lib/query";
import { ago } from "@/lib/format";

type Repo = {
  repository_id: string; workspace: string; slug: string; status: string;
  error?: string | null; last_run: string | null; detail_done: number; detail_total: number;
};
type Source = {
  connector: string; label: string; scope: string; status: string; error?: string | null;
  failed?: boolean; last_run: string | null;
};
type Refresh = {
  running?: boolean; source?: string; full?: boolean; started_at?: string | null;
  error?: string | null; finished_at?: string | null; summary?: string | null;
};
type Settings = {
  report_tz: string; window_days: number; overlap_hours: number; refresh_after_minutes: number;
  database: string; credentials: Record<string, boolean>;
};

function Note({ children }: { children: React.ReactNode }) {
  return <Text type="supporting" as="p">{children}</Text>;
}

function Failure({ error }: { error: unknown }) {
  return <Banner status="error" title={(error as Error).message} />;
}

export function SelectionView() {
  const repos = useApi("/api/repos");
  const write = useWrite();
  const [text, setText] = useState("");
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);
  const list = (repos.data as { repos: Repo[] } | undefined)?.repos;

  async function add() {
    const value = text.trim();
    if (!value) return;
    setMessage("Checking…");
    setFailed(false);
    try {
      const r = (await write("/api/repos", "POST", {
        repo: value.indexOf(":") > 0 ? value : "bitbucket:" + value,
      })) as { workspace: string; slug: string };
      setMessage(`Added ${r.workspace}/${r.slug}.`);
      setText("");
    } catch (e) {
      setMessage((e as Error).message);
      setFailed(true);
    }
  }

  async function remove(r: Repo) {
    if (!window.confirm(`Stop syncing ${r.workspace}/${r.slug}? Stored data is kept.`)) return;
    try {
      await write("/api/repos/" + encodeURIComponent(r.repository_id), "DELETE");
    } catch (e) {
      window.alert((e as Error).message);
    }
  }

  const columns = [
    {
      key: "repo",
      header: "Repository",
      renderCell: (r: Repo) => (
        <VStack>
          <Text weight="semibold">{r.workspace}/{r.slug}</Text>
          <Text type="supporting">{r.repository_id}</Text>
        </VStack>
      ),
    },
    {
      key: "status",
      header: "Status",
      renderCell: (r: Repo) => (
        <Text color={r.status === "failed" ? "accent" : "primary"}>{r.status + (r.error ? ": " + r.error : "")}</Text>
      ),
    },
    { key: "last_run", header: "Last sync", renderCell: (r: Repo) => ago(r.last_run) },
    { key: "detail", header: "Review detail", renderCell: (r: Repo) => `${r.detail_done} of ${r.detail_total}` },
    {
      key: "remove",
      header: "",
      renderCell: (r: Repo) => <Button label="Remove" variant="destructive" onClick={() => remove(r)} />,
    },
  ];

  return (
    <VStack gap={3}>
      <Heading level={2}>Selection</Heading>
      <Note>
        Repositories that are synced. Add one by workspace/slug, slug (with BITBUCKET_WORKSPACE set) or UUID; access is checked first.
      </Note>
      <HStack gap={2} align="end">
        <TextInput
          label="Repository"
          placeholder="workspace/repository"
          width={360}
          value={text}
          onChange={setText}
          onEnter={add}
          status={failed ? { type: "error", message } : undefined}
        />
        <Button label="Add repository" variant="primary" onClick={add} />
        {!failed && message ? <Text type="supporting">{message}</Text> : null}
      </HStack>
      {repos.error ? (
        <Failure error={repos.error} />
      ) : list ? (
        <Table
          data={list}
          columns={columns}
          idKey="repository_id"
          emptyState={<Note>No repositories are selected yet.</Note>}
        />
      ) : null}
      <Note>Jira projects are added here when the Jira connector lands.</Note>
    </VStack>
  );
}

function stateText(refresh: Refresh): string {
  if (refresh.running) {
    return `Refreshing${refresh.source ? " " + refresh.source : ""}${refresh.full ? " (full)" : ""} since ${ago(refresh.started_at ?? null)}…`;
  }
  if (refresh.error) return "Last refresh failed: " + refresh.error;
  if (refresh.finished_at) return `Last refresh ${ago(refresh.finished_at)}: ${refresh.summary || "done"}`;
  return "No refresh has run since the app started.";
}

export function SourcesView() {
  const sources = useApi("/api/sources");
  const repos = useApi("/api/repos");
  const write = useWrite();
  const data = sources.data as
    | { sources: Source[]; configured: string[]; waiting: string[]; refresh: Refresh }
    | undefined;
  const detail: Record<string, string> = {};
  for (const r of (repos.data as { repos: Repo[] } | undefined)?.repos ?? []) {
    detail[r.repository_id] = `${r.detail_done} of ${r.detail_total}`;
  }

  async function refresh(body: Record<string, unknown>) {
    try {
      await write("/api/refresh", "POST", body);
      await recheckVersion();
    } catch (e) {
      window.alert("Refresh failed: " + (e as Error).message);
    }
  }

  const columns = [
    { key: "connector", header: "Source" },
    { key: "label", header: "Scope" },
    {
      key: "status",
      header: "Status",
      renderCell: (s: Source) => (
        <Text color={s.failed ? "accent" : "primary"}>{s.status + (s.error ? ": " + s.error : "")}</Text>
      ),
    },
    { key: "last_run", header: "Last sync", renderCell: (s: Source) => ago(s.last_run) },
    { key: "detail", header: "Review detail", renderCell: (s: Source) => detail[s.scope] || "–" },
    {
      key: "resync",
      header: "",
      renderCell: (s: Source) => (
        <Button
          label="Full resync"
          onClick={() => {
            if (window.confirm(`Clear the ${s.connector} cursor and sync its whole window again?`)) {
              refresh({ source: s.connector, full: true });
            }
          }}
        />
      ),
    },
  ];

  return (
    <VStack gap={3}>
      <Heading level={2}>Sources</Heading>
      <HStack gap={2} align="center">
        <Button label="Refresh now" variant="primary" onClick={() => refresh({})} />
        {data ? <Text type="supporting">{stateText(data.refresh)}</Text> : null}
      </HStack>
      {sources.error ? (
        <Failure error={sources.error} />
      ) : data ? (
        <>
          <Table
            data={data.sources}
            columns={columns}
            idKey={(s: Source) => s.connector + s.scope}
            emptyState={
              <Note>
                {data.configured.length ? "Nothing synced yet. Use Refresh now." : "No connectors are configured. Put BITBUCKET in .env."}
              </Note>
            }
          />
          {data.sources.length && data.waiting.length ? <Note>Not connected yet: {data.waiting.join(", ")}.</Note> : null}
        </>
      ) : null}
      <Note>
        A full resync clears a source&apos;s cursor so the next sync walks its whole window again. Stored data is kept.
      </Note>
    </VStack>
  );
}

type SettingRow = { name: string; value: string };

export function SettingsView() {
  const q = useApi("/api/settings");
  const s = q.data as Settings | undefined;
  const rows: SettingRow[] = s
    ? [
        { name: "Report time zone", value: s.report_tz },
        { name: "Default window", value: s.window_days + " days" },
        { name: "Re-sync overlap", value: s.overlap_hours + " hours" },
        { name: "Refresh after", value: s.refresh_after_minutes + " minutes (REFRESH_AFTER_MINUTES)" },
        { name: "Database", value: s.database },
        ...Object.keys(s.credentials).map((n) => ({ name: n, value: s.credentials[n] ? "present" : "missing" })),
      ]
    : [];
  return (
    <VStack gap={3}>
      <Heading level={2}>Settings</Heading>
      {q.error ? (
        <Failure error={q.error} />
      ) : s ? (
        <Table
          data={rows}
          idKey="name"
          columns={[
            { key: "name", header: "Setting" },
            { key: "value", header: "Value" },
          ]}
        />
      ) : null}
      <Note>
        Change these in .env and restart the app. Jira status and story-point mapping appear here when the Jira connector lands.
      </Note>
    </VStack>
  );
}

export function AskView() {
  return (
    <VStack gap={3}>
      <Heading level={2}>Ask</Heading>
      <Note>
        Ask questions about the data in plain language. This arrives with the MCP and Ask spec: Claude will answer using the same metrics as these screens and show the query it used.
      </Note>
    </VStack>
  );
}
