"use client";

import { useState, type ReactNode } from "react";
import NextLink from "next/link";
import { useSearchParams } from "next/navigation";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Heading } from "@astryxdesign/core/Heading";
import { HStack } from "@astryxdesign/core/HStack";
import { Link } from "@astryxdesign/core/Link";
import { Selector } from "@astryxdesign/core/Selector";
import { Table, type TableColumn } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/VStack";
import { useApi } from "@/lib/query";
import { filterQuery, useFilters, useSetParam } from "@/lib/filters";
import { UpliftChart } from "@/components/charts/UpliftCharts";

export const CUSTOM = "people:";

type Option = { value: string; label: string; size?: number | null };
type Side = { count: number; of: number } | null | undefined;
type Block = { value: number | null; median: number | null; partial?: boolean };
type Person = {
  person_id: string; name: string; level: string; day_reached: number;
  at_or_above_median?: { before?: Side; after?: Side }; grid: Block[]; points: unknown;
};
type Cohort = {
  compare?: { value: string; label: string; note?: string };
  coverage?: Record<string, string | null>; people: Person[];
};

export function coverageLine(c: Record<string, string | null> | undefined): string {
  return Object.keys(c ?? {}).map((k) => k.replace(/_/g, " ") + ": " + (c?.[k] || "–")).join(" · ");
}

/** The "Compare against" choice lives in the URL as compare= (everyone when absent). */
export function useCompare() {
  const params = useSearchParams();
  const compare = params.get("compare") ?? "";
  const isCustom = compare.startsWith(CUSTOM);
  const ids = isCustom ? compare.slice(CUSTOM.length).split(",").filter(Boolean) : [];
  return { compare, isCustom, ids };
}

function PeoplePicker({ selected, onApply }: { selected: string[]; onApply: (ids: string[]) => void }) {
  const filters = useFilters();
  const people = useApi("/api/people" + filterQuery(filters));
  const [chosen, setChosen] = useState<string[]>(selected);
  const list = (people.data as { people?: { person_id: string; name: string }[] } | undefined)?.people ?? [];
  if (people.error) return <Banner status="error" title={(people.error as Error).message} />;
  const toggle = (id: string, on: boolean) => setChosen((c) => (on ? [...c.filter((x) => x !== id), id] : c.filter((x) => x !== id)));
  return (
    <Card>
      <VStack gap={2}>
        <HStack gap={2} align="center" wrap="wrap">
          <Button label="Select all" variant="secondary" onClick={() => setChosen(list.map((p) => p.person_id))} />
          <Button label="Clear" variant="secondary" onClick={() => setChosen([])} />
          <Button label="Apply" isDisabled={chosen.length < 2} onClick={() => onApply(chosen)} />
          <Text color="secondary">{chosen.length < 2 ? "Pick at least 2 people" : chosen.length + " people ticked"}</Text>
        </HStack>
        {list.map((p) => (
          <CheckboxInput key={p.person_id} label={p.name} value={chosen.includes(p.person_id)} onChange={(on) => toggle(p.person_id, on)} />
        ))}
      </VStack>
    </Card>
  );
}

/** Compare-against selector plus the custom people checklist. */
export function ComparePicker({ info }: { info?: { value: string; label: string; note?: string } }) {
  const { compare, isCustom, ids } = useCompare();
  const setParam = useSetParam();
  const options = useApi("/api/uplift/compare-options");
  const [pickingCustom, setPickingCustom] = useState(false);
  const list = (options.data as { options?: Option[] } | undefined)?.options ?? [];
  const items = list.map((o) => {
    let label = o.size === null || o.size === undefined ? o.label : `${o.label} (${o.size})`;
    if (o.value === CUSTOM && isCustom) label = info?.value === compare ? info.label : ids.length + " chosen people";
    return { value: o.value, label };
  });
  const value = isCustom ? CUSTOM : compare || "everyone";
  return (
    <VStack gap={2}>
      <Selector
        label="Compare against" options={items} value={value}
        onChange={(v) => {
          if (v === CUSTOM) { setPickingCustom(true); return; }
          setPickingCustom(false);
          setParam("compare", v === "everyone" ? "" : v);
        }}
      />
      {(pickingCustom || isCustom) && (
        <PeoplePicker selected={ids} onApply={(picked) => { setPickingCustom(false); setParam("compare", CUSTOM + picked.join(",")); }} />
      )}
      {info?.note ? <Text color="secondary">{info.note}</Text> : null}
    </VStack>
  );
}

const ofCount = (side: Side) => (side ? `${side.count} of ${side.of}` : "–");

type GridRow = Record<string, unknown> & { id: string; person: Person };

function BlockGrid({ people }: { people: Person[] }) {
  if (!people.length) return <Text color="secondary">Nobody is in the cohort yet. Add people with the cohort command.</Text>;
  const width = Math.max(...people.map((p) => p.grid.length));
  const data: GridRow[] = people.map((p) => ({ id: p.person_id, person: p }));
  const columns: TableColumn<GridRow>[] = [
    { key: "name", header: "Person", renderCell: ({ person }) => person.name },
    { key: "level", header: "Level", renderCell: ({ person }) => person.level },
    ...Array.from({ length: width }, (_, i) => ({
      key: "block" + i, header: "Block " + i,
      renderCell: ({ person }: GridRow) => {
        const b = person.grid[i];
        const text = !b ? "–" : (b.value === null ? "–" : String(b.value)) + (b.partial ? " (running)" : "");
        const good = b && b.value !== null && b.median !== null && b.value >= b.median;
        return <Text color={good ? "accent" : "primary"} data-kind={good ? "good" : ""}>{text}</Text>;
      },
    })),
  ];
  return <Table<GridRow> data={data} columns={columns} idKey="id" />;
}

export function Uplift() {
  const { compare } = useCompare();
  const filters = useFilters();
  const cohort = useApi("/api/uplift/cohort" + filterQuery(filters, { compare }));
  const d = cohort.data as Cohort | undefined;

  let body: ReactNode;
  if (cohort.error) body = <Banner status="error" title={(cohort.error as Error).message} />;
  else if (!d) body = <Text color="secondary">Loading the cohort… this can take a minute.</Text>;
  else {
    body = (
      <VStack gap={3}>
        <Text color="secondary">{"Data covered up to " + coverageLine(d.coverage)}</Text>
        {d.people.map((p) => (
          <Card key={p.person_id}>
            <VStack gap={1}>
              <Heading level={3}>
                <Link as={NextLink} href={"/uplift/person" + filterQuery(filters, { id: p.person_id, compare })}>{p.name}</Link>
              </Heading>
              <Text color="secondary">
                {`${p.level} · Day ${p.day_reached} of 90 · blocks at or above the median of the comparison group, before Day 0: ${ofCount(p.at_or_above_median?.before)}, after: ${ofCount(p.at_or_above_median?.after)}`}
              </Text>
              <UpliftChart cohort={p.points} compare={compare} />
            </VStack>
          </Card>
        ))}
        <Card>
          <VStack gap={2}>
            <Heading level={3}>Blocks at a glance</Heading>
            <BlockGrid people={d.people} />
          </VStack>
        </Card>
      </VStack>
    );
  }

  return (
    <VStack as="main" gap={3}>
      <Heading level={2}>AI uplift</Heading>
      <ComparePicker info={d?.compare} />
      {body}
    </VStack>
  );
}
