import { HydrationBoundary } from "@tanstack/react-query";
import { prefetch } from "@/lib/server-api";
import { SourcesView } from "@/components/pages/Setup";

export const dynamic = "force-dynamic";

export default async function Page() {
  const state = await prefetch(["/api/sources", "/api/repos"]);
  return (
    <HydrationBoundary state={state}>
      <SourcesView />
    </HydrationBoundary>
  );
}
