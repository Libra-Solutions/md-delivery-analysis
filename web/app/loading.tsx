// Shown at once on every navigation while the next page renders on the server.
import { Spinner } from "@astryxdesign/core/Spinner";

export default function Loading() {
  return <Spinner label="Loading…" />;
}
