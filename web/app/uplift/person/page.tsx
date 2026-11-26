import { HydrationBoundary } from "@tanstack/react-query";
import { prefetch } from "@/lib/server-api";
import { UpliftPerson } from "@/components/pages/UpliftPerson";

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const id = typeof sp.id === "string" ? sp.id : "";
  const compare = typeof sp.compare === "string" ? sp.compare : "";
  const params = new URLSearchParams();
  const get = (k: string) => (typeof sp[k] === "string" ? (sp[k] as string) : "");
  if (get("team")) params.set("team", get("team"));
  if (get("window")) params.set("window", get("window"));
  if (get("window") === "custom") { params.set("from", get("from")); params.set("to", get("to")); }
  if (compare) params.set("compare", compare);
  const query = params.toString() ? "?" + params.toString() : "";
  const paths = ["/api/uplift/compare-options"];
  if (id) paths.push("/api/uplift/person/" + encodeURIComponent(id) + query);
  const state = await prefetch(paths);
  return (
    <HydrationBoundary state={state}>
      <UpliftPerson />
    </HydrationBoundary>
  );
}
