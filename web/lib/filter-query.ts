export type Filters = {
  team: string;
  window: string;
  from: string;
  to: string;
  metric: string;
  inactive: string;
  id: string;
};

export function filterQuery(f: Partial<Filters>, extra?: Record<string, string | undefined>): string {
  const params = new URLSearchParams();
  if (f.team) {
    params.set("team", f.team);
  }
  if (f.window) {
    params.set("window", f.window);
  }
  if (f.window === "custom") {
    params.set("from", f.from ?? "");
    params.set("to", f.to ?? "");
  }
  Object.keys(extra ?? {}).forEach((key) => {
    const value = extra?.[key];
    if (value !== undefined && value !== "") {
      params.set(key, value);
    }
  });
  const text = params.toString();
  return text ? `?${text}` : "";
}

export function windowOptions(now: Date): [string, string][] {
  const options: [string, string][] = [
    ["", "Team default"],
    ["30d", "Last 30 days"],
    ["90d", "Last 90 days"],
  ];
  for (let i = 0; i < 6; i += 1) {
    const month = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const value = `month:${month.getFullYear()}-${String(month.getMonth() + 1).padStart(2, "0")}`;
    options.push([value, month.toLocaleString("en-US", { month: "long", year: "numeric" })]);
  }
  options.push(["custom", "Custom dates"]);
  return options;
}
