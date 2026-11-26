import { HydrationBoundary } from "@tanstack/react-query";
import { prefetch } from "@/lib/server-api";
import { SelectionView } from "@/components/pages/Setup";

export const dynamic = "force-dynamic";

export default async function Page() {
  const state = await prefetch(["/api/repos"]);
  return (
    <HydrationBoundary state={state}>
      <SelectionView />
    </HydrationBoundary>
  );
}
