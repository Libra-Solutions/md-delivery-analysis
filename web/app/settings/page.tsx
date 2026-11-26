import { HydrationBoundary } from "@tanstack/react-query";
import { prefetch } from "@/lib/server-api";
import { SettingsView } from "@/components/pages/Setup";

export const dynamic = "force-dynamic";

export default async function Page() {
  const state = await prefetch(["/api/settings"]);
  return (
    <HydrationBoundary state={state}>
      <SettingsView />
    </HydrationBoundary>
  );
}
