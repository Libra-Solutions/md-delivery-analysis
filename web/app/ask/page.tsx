import { HydrationBoundary } from "@tanstack/react-query";
import { prefetch } from "@/lib/server-api";
import { AskView } from "@/components/pages/Setup";

export const dynamic = "force-dynamic";

export default async function Page() {
  const state = await prefetch([]);
  return (
    <HydrationBoundary state={state}>
      <AskView />
    </HydrationBoundary>
  );
}
