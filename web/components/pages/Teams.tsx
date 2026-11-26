"use client";

import { useEffect, useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Heading } from "@astryxdesign/core/Heading";
import { Selector } from "@astryxdesign/core/Selector";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Table } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useApi, useWrite } from "@/lib/query";
import { useFilters, useSetParam } from "@/lib/filters";

type TeamRow = {
  team_id: string; name: string; repos: { repository_id: string; name?: string }[];
  members: { active: number; inactive: number; excluded: number };
};
type Repo = { repository_id: string; slug: string };
type Member = {
  person_id: string; name: string; status: string; manual?: boolean;
  last_commit: string | null; emails: string[];
};
type TeamDetail = {
  team_id: string; name: string; members: Member[];
  possible_duplicates: { name_a: string; name_b: string; reason: string }[];
};
type Unmapped = { source: string; account: string; name_hint?: string | null; activity: number };
type Person = { person_id: string; name: string };
type Comparison = { people: { person_id: string; name: string; selected: boolean }[] };

const NEW_PERSON = "__new__";

function Note({ children }: { children: React.ReactNode }) {
  return <Text type="supporting" as="p">{children}</Text>;
}

function Failure({ error }: { error: unknown }) {
  return <Banner status="error" title={(error as Error).message} />;
}

function fail(e: unknown) {
  window.alert((e as Error).message);
}

function TeamList({ teams }: { teams: TeamRow[] }) {
  const setParam = useSetParam();
  const columns = [
    {
      key: "name",
      header: "Team",
      renderCell: (t: TeamRow) => <Button label={t.name} variant="ghost" onClick={() => setParam("team", t.team_id)} />,
    },
    { key: "repos", header: "Repositories", renderCell: (t: TeamRow) => t.repos.map((r) => r.name || r.repository_id).join(", ") },
    { key: "active", header: "Active", renderCell: (t: TeamRow) => String(t.members.active) },
    { key: "inactive", header: "Inactive", renderCell: (t: TeamRow) => String(t.members.inactive) },
    { key: "excluded", header: "Excluded", renderCell: (t: TeamRow) => String(t.members.excluded) },
  ];
  return (
    <Table
      data={teams}
      columns={columns}
      idKey="team_id"
      emptyState={<Note>No teams yet. Create one below from the selected repositories.</Note>}
    />
  );
}

function CreateTeam({ repos }: { repos: Repo[] }) {
  const write = useWrite();
  const setParam = useSetParam();
  const [name, setName] = useState("");
  const [off, setOff] = useState<Record<string, boolean>>({});
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);

  async function create() {
    const chosen = repos.filter((r) => !off[r.repository_id]).map((r) => "bitbucket:" + r.repository_id);
    setFailed(false);
    try {
      const r = (await write("/api/teams", "POST", { name, repos: chosen })) as { team_id: string; summary: string };
      setMessage(r.summary);
      setParam("team", r.team_id);
    } catch (e) {
      setMessage((e as Error).message);
      setFailed(true);
    }
  }

  return (
    <VStack gap={2}>
      <Heading level={3}>Create a team</Heading>
      <HStack gap={3} align="end" wrap="wrap">
        <TextInput label="Team name" placeholder="Team name" width={260} value={name} onChange={setName} />
        {repos.map((r) => (
          <CheckboxInput
            key={r.repository_id}
            label={r.slug}
            value={!off[r.repository_id]}
            onChange={(checked) => setOff({ ...off, [r.repository_id]: !checked })}
          />
        ))}
        <Button label="Create from these repositories" variant="primary" onClick={create} />
      </HStack>
      {message ? failed ? <Banner status="error" title={message} /> : <Text type="supporting">{message}</Text> : null}
    </VStack>
  );
}

function Members({ teamId }: { teamId: string }) {
  const detail = useApi("/api/teams/" + encodeURIComponent(teamId));
  const write = useWrite();
  const team = detail.data as TeamDetail | undefined;

  async function toggle(m: Member) {
    const next = m.status === "excluded" ? "active" : "excluded";
    try {
      await write(`/api/teams/${encodeURIComponent(teamId)}/members/${encodeURIComponent(m.person_id)}`, "POST", { status: next });
    } catch (e) {
      fail(e);
    }
  }

  const columns = [
    { key: "name", header: "Person", renderCell: (m: Member) => m.name },
    { key: "status", header: "Status", renderCell: (m: Member) => m.status + (m.manual ? " (set by you)" : "") },
    { key: "last", header: "Last commit", renderCell: (m: Member) => (m.last_commit ? m.last_commit.slice(0, 10) : "–") },
    { key: "emails", header: "Emails", renderCell: (m: Member) => m.emails.join(", ") },
    {
      key: "act",
      header: "",
      renderCell: (m: Member) => (
        <Button label={m.status === "excluded" ? "Include" : "Exclude"} onClick={() => toggle(m)} />
      ),
    },
  ];

  return (
    <VStack gap={2}>
      <Heading level={3}>{team ? "Members of " + team.name : "Members"}</Heading>
      {detail.error ? <Failure error={detail.error} /> : null}
      {team ? <Table data={team.members} columns={columns} idKey="person_id" /> : null}
      {team && team.possible_duplicates.length ? (
        <VStack>
          <Note>Possible duplicates (merge with the teams CLI if they are the same person):</Note>
          {team.possible_duplicates.map((d, i) => (
            <Text key={i}>{`${d.name_a} and ${d.name_b} (${d.reason})`}</Text>
          ))}
        </VStack>
      ) : null}
    </VStack>
  );
}

function CompareGroup({ teamId }: { teamId: string }) {
  const data = useApi("/api/teams/" + encodeURIComponent(teamId) + "/comparison");
  const write = useWrite();
  const people = (data.data as Comparison | undefined)?.people;
  const [picked, setPicked] = useState<Record<string, boolean> | null>(null);

  useEffect(() => {
    setPicked(null);
  }, [teamId]);

  if (!people) return null;
  const on = (id: string, selected: boolean) => (picked ? Boolean(picked[id]) : selected);

  async function put(ids: string[] | null) {
    try {
      await write(`/api/teams/${encodeURIComponent(teamId)}/comparison`, "PUT", { person_ids: ids });
      setPicked(null);
    } catch (e) {
      fail(e);
    }
  }

  return (
    <VStack gap={2}>
      <Heading level={3}>Comparison group</Heading>
      <Note>People the AI uplift charts compare against. By default the whole active team.</Note>
      <HStack gap={3} wrap="wrap">
        {people.map((p) => (
          <CheckboxInput
            key={p.person_id}
            label={p.name}
            value={on(p.person_id, p.selected)}
            onChange={(checked) => {
              const base = Object.fromEntries(people.map((q) => [q.person_id, on(q.person_id, q.selected)]));
              setPicked({ ...base, [p.person_id]: checked });
            }}
          />
        ))}
      </HStack>
      <HStack gap={2}>
        <Button
          label="Save comparison group"
          variant="primary"
          onClick={() => put(people.filter((p) => on(p.person_id, p.selected)).map((p) => p.person_id))}
        />
        <Button label="Reset to whole team" onClick={() => put(null)} />
      </HStack>
    </VStack>
  );
}

function UnmappedRow({ u, people, team }: { u: Unmapped; people: Person[]; team: string }) {
  const write = useWrite();
  const [who, setWho] = useState<string>(NEW_PERSON);
  const [name, setName] = useState(u.name_hint || "");
  const [join, setJoin] = useState(Boolean(team));

  async function map() {
    const body: Record<string, unknown> = { source: u.source, account: u.account, team_id: join && team ? team : null };
    if (who !== NEW_PERSON) body.person_id = who;
    else body.new_name = name;
    try {
      await write("/api/identities", "POST", body);
    } catch (e) {
      fail(e);
    }
  }

  return (
    <HStack gap={3} align="end" wrap="wrap">
      <VStack>
        <Text weight="semibold">{u.name_hint || "Unknown name"}</Text>
        <Text type="supporting">{u.source + ":" + u.account}</Text>
      </VStack>
      <Text>{`Activity ${u.activity}`}</Text>
      <Selector
        label="Person"
        isLabelHidden
        value={who}
        onChange={(v) => setWho(v ?? NEW_PERSON)}
        options={[{ value: NEW_PERSON, label: "New person…" }, ...people.map((p) => ({ value: p.person_id, label: p.name }))]}
        width={200}
      />
      <TextInput label="New person name" isLabelHidden placeholder="Name" width={200} value={name} onChange={setName} />
      <CheckboxInput label="add to this team" value={join && Boolean(team)} isDisabled={!team} onChange={setJoin} />
      <Button label="Map" onClick={map} />
    </HStack>
  );
}

export function TeamsView() {
  const { team } = useFilters();
  const teams = useApi("/api/teams");
  const repos = useApi("/api/repos");
  const unmapped = useApi("/api/identities/unmapped");
  const list = (teams.data as { teams: TeamRow[] } | undefined)?.teams;
  const repoList = (repos.data as { repos: Repo[] } | undefined)?.repos ?? [];
  const un = unmapped.data as { unmapped: Unmapped[]; people: Person[] } | undefined;

  return (
    <VStack gap={4}>
      <Heading level={2}>Teams</Heading>
      {teams.error ? <Failure error={teams.error} /> : list ? <TeamList teams={list} /> : null}
      <CreateTeam repos={repoList} />
      {team ? (
        <>
          <Members teamId={team} />
          <CompareGroup teamId={team} />
        </>
      ) : (
        <Note>Pick a team in the header to see and edit its members.</Note>
      )}
      <VStack gap={2}>
        <Heading level={3}>Unmapped accounts</Heading>
        <Note>Activity by these accounts is counted in an &quot;Unmapped&quot; row until you say who they are.</Note>
        {unmapped.error ? (
          <Failure error={unmapped.error} />
        ) : un ? (
          un.unmapped.length ? (
            un.unmapped.map((u) => <UnmappedRow key={u.source + ":" + u.account} u={u} people={un.people} team={team} />)
          ) : (
            <Note>Every account with activity is mapped to a person.</Note>
          )
        ) : null}
      </VStack>
    </VStack>
  );
}
