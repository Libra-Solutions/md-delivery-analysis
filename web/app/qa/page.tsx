import { HydrationBoundary } from "@tanstack/react-query";
import { prefetch } from "@/lib/server-api";
import { Qa } from "@/components/pages/Qa";

export default async function Page() {
  const state = await prefetch(["/api/qa"]);
  return (
    <HydrationBoundary state={state}>
      <Qa />
    </HydrationBoundary>
  );
}
