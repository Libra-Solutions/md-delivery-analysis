"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { Filters } from "./filter-query";

export { filterQuery, windowOptions, type Filters } from "./filter-query";

export function useFilters(): Filters {
  const params = useSearchParams();
  const get = (name: string) => params.get(name) ?? "";
  return {
    team: get("team"),
    window: get("window"),
    from: get("from"),
    to: get("to"),
    metric: get("metric"),
    inactive: get("inactive"),
    id: get("id"),
  };
}

export function useSetParam(): (name: string, value: string) => void {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  return (name: string, value: string) => {
    const next = new URLSearchParams(params.toString());
    if (value) {
      next.set(name, value);
    } else {
      next.delete(name);
    }
    const text = next.toString();
    router.replace(pathname + (text ? `?${text}` : ""), { scroll: false });
  };
}
