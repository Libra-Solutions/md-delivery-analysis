import { HydrationBoundary } from "@tanstack/react-query";
import { prefetch } from "@/lib/server-api";
import { Uplift } from "@/components/pages/Uplift";

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const compare = typeof sp.compare === "string" ? sp.compare : "";
  const params = new URLSearchParams();
  const get = (k: string) => (typeof sp[k] === "string" ? (sp[k] as string) : "");
  if (get("team")) params.set("team", get("team"));
  if (get("window")) params.set("window", get("window"));
  if (get("window") === "custom") { params.set("from", get("from")); params.set("to", get("to")); }
  if (compare) params.set("compare", compare);
  const query = params.toString() ? "?" + params.toString() : "";
  const state = await prefetch(["/api/uplift/compare-options", "/api/uplift/cohort" + query]);
  return (
    <HydrationBoundary state={state}>
      <Uplift />
    </HydrationBoundary>
  );
}
