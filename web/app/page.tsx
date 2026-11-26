import { HydrationBoundary } from "@tanstack/react-query";
import { Dashboard } from "@/components/pages/Dashboard";
import { filterQuery, type Filters } from "@/lib/filter-query";
import { prefetch } from "@/lib/server-api";

const METRICS = [
  "story_points_weekly", "story_points_done", "points_by_type", "cycle_time_weekly", "cycle_time_summary",
  "prs_linked_weekly", "prs_with_issue_link", "story_points_per_dollar_weekly", "story_points_per_dollar",
  "story_points_per_dollar_all_in", "unattributed_cost_share", "cost_by_purpose_weekly", "ask_generate_ratio",
  "prs_merged_weekly", "issues_done_weekly", "time_to_merge", "lead_time_breakdown", "review_load", "work_in_progress",
];

type Search = Record<string, string | string[] | undefined>;
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";

export default async function Page({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const f: Filters = {
    team: one(sp.team), window: one(sp.window), from: one(sp.from), to: one(sp.to),
    metric: one(sp.metric), inactive: one(sp.inactive), id: one(sp.id),
  };
  const q = filterQuery(f);
  const state = await prefetch([...METRICS.map((m) => `/api/metrics/${m}${q}`), "/api/metrics"]);
  return (
    <HydrationBoundary state={state}>
      <Dashboard />
    </HydrationBoundary>
  );
}
