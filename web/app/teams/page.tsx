import { HydrationBoundary } from "@tanstack/react-query";
import { prefetch } from "@/lib/server-api";
import { TeamsView } from "@/components/pages/Teams";

export const dynamic = "force-dynamic";

export default async function Page() {
  const state = await prefetch(["/api/teams", "/api/repos", "/api/identities/unmapped"]);
  return (
    <HydrationBoundary state={state}>
      <TeamsView />
    </HydrationBoundary>
  );
}
