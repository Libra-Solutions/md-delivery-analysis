import { HydrationBoundary } from "@tanstack/react-query";
import { prefetch } from "@/lib/server-api";
import { Rankings } from "@/components/pages/Rankings";

export default async function Page() {
  const state = await prefetch(["/api/metrics"]);
  return (
    <HydrationBoundary state={state}>
      <Rankings />
    </HydrationBoundary>
  );
}
