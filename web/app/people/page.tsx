import { HydrationBoundary } from "@tanstack/react-query";
import { prefetch } from "@/lib/server-api";
import { People } from "@/components/pages/People";

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const get = (k: string) => (typeof sp[k] === "string" ? (sp[k] as string) : "");
  const params = new URLSearchParams();
  if (get("team")) params.set("team", get("team"));
  if (get("window")) params.set("window", get("window"));
  if (get("window") === "custom") { params.set("from", get("from")); params.set("to", get("to")); }
  if (get("inactive") === "1") params.set("include_inactive", "true");
  const query = params.toString() ? "?" + params.toString() : "";
  const state = await prefetch(["/api/people-matrix" + query]);
  return (
    <HydrationBoundary state={state}>
      <People />
    </HydrationBoundary>
  );
}
