import { HydrationBoundary } from "@tanstack/react-query";
import { Person } from "@/components/pages/Person";
import { filterQuery, type Filters } from "@/lib/filter-query";
import { prefetch } from "@/lib/server-api";

type Search = Record<string, string | string[] | undefined>;
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";

export default async function Page({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const f: Filters = {
    team: one(sp.team), window: one(sp.window), from: one(sp.from), to: one(sp.to),
    metric: one(sp.metric), inactive: one(sp.inactive), id: one(sp.id),
  };
  const paths = ["/api/teams", "/api/people" + filterQuery(f, { include_inactive: "true" })];
  if (f.id) {
    paths.push(
      "/api/people/" + encodeURIComponent(f.id) + filterQuery(f),
      "/api/tickets" + filterQuery(f, { person: f.id }),
    );
  }
  const state = await prefetch(paths);
  return (
    <HydrationBoundary state={state}>
      <Person />
    </HydrationBoundary>
  );
}
