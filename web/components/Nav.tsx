"use client";

import NextLink from "next/link";
import { usePathname } from "next/navigation";
import { SideNav, SideNavHeading, SideNavItem, SideNavSection } from "@astryxdesign/core/SideNav";
import { filterQuery, useFilters } from "@/lib/filters";

type Item = { href: string; label: string };

export const MAIN_LINKS: Item[] = [
  { href: "/", label: "Dashboard" },
  { href: "/person", label: "People" },
  { href: "/uplift", label: "AI uplift" },
  { href: "/ai-year", label: "AI year" },
  { href: "/rankings", label: "Rankings" },
  { href: "/qa", label: "QA" },
  { href: "/ask", label: "Ask" },
];

export const SETUP_LINKS: Item[] = [
  { href: "/selection", label: "Selection" },
  { href: "/teams", label: "Teams" },
  { href: "/sources", label: "Sources" },
  { href: "/settings", label: "Settings" },
];

function isActive(href: string, path: string): boolean {
  if (href === "/person") return path === "/people" || path.startsWith("/people/") || path === "/person";
  return path === href;
}

export function Nav() {
  const path = usePathname() ?? "/";
  const query = filterQuery(useFilters());
  const item = (it: Item) => (
    <SideNavItem
      key={it.href}
      as={NextLink}
      label={it.label}
      href={`${it.href}${query}`}
      isSelected={isActive(it.href, path)}
    />
  );
  return (
    <SideNav header={<SideNavHeading heading="Delivery Analytics" />}>
      <SideNavSection title="Analytics" isHeaderHidden>
        {MAIN_LINKS.map(item)}
      </SideNavSection>
      <SideNavSection title="Set up">{SETUP_LINKS.map(item)}</SideNavSection>
    </SideNav>
  );
}
