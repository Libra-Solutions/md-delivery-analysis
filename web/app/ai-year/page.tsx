import { HydrationBoundary } from "@tanstack/react-query";
import { prefetch } from "@/lib/server-api";
import { AiYear } from "@/components/pages/AiYear";

export default async function Page() {
  const state = await prefetch(["/api/uplift/year/people", "/api/uplift/compare-options"]);
  return (
    <HydrationBoundary state={state}>
      <AiYear />
    </HydrationBoundary>
  );
}
