"use client";

import { useEffect, useState, type ReactNode } from "react";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister";
import { del, get, set } from "idb-keyval";
import {
  SEVEN_DAYS,
  VERSION_KEY,
  VersionContext,
  dropStaleQueries,
  makeQueryClient,
  setQueryClient,
  useVersionQuery,
} from "@/lib/query";

const BUILD_ID = process.env.NEXT_PUBLIC_BUILD_ID ?? "dev";

const hasIdb = () => typeof indexedDB !== "undefined";

// Same component tree on server and client; storage is a no-op without IndexedDB.
function createPersister() {
  return createAsyncStoragePersister({
    storage: {
      getItem: async (key) => (hasIdb() ? ((await get(key)) ?? null) : null),
      setItem: async (key, value) => {
        if (hasIdb()) await set(key, value);
      },
      removeItem: async (key) => {
        if (hasIdb()) await del(key);
      },
    },
  });
}

/** Polls the data version (mount, focus, every 60 s) and drops queries of old versions. */
function VersionWatcher({ client }: { client: ReturnType<typeof makeQueryClient> }) {
  const q = useVersionQuery({ watch: true });
  const version = q.data;
  useEffect(() => {
    if (version) dropStaleQueries(client, version);
  }, [client, version]);
  return null;
}

export function Providers({ version, children }: { version: string; children: ReactNode }) {
  const [client] = useState(() => {
    const c = makeQueryClient();
    setQueryClient(c);
    return c;
  });
  const [persister] = useState(createPersister);

  const inner = (
    <VersionContext.Provider value={version}>
      <VersionWatcher client={client} />
      {children}
    </VersionContext.Provider>
  );

  return (
    <PersistQueryClientProvider
      client={client}
      persistOptions={{
        persister,
        buster: BUILD_ID,
        maxAge: SEVEN_DAYS,
        dehydrateOptions: { shouldDehydrateQuery: (q) => q.queryKey[0] !== VERSION_KEY && q.state.status === "success" },
      }}
      onSuccess={() => dropStaleQueries(client, client.getQueryData<string>([VERSION_KEY]) ?? version)}
    >
      {inner}
    </PersistQueryClientProvider>
  );
}
