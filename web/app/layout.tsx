import type { ReactNode } from "react";
import "./globals.css";
import { AppShell } from "@astryxdesign/core/AppShell";
import { Theme } from "@astryxdesign/core/theme";
import { VStack } from "@astryxdesign/core/Stack";
import { themes, defaultThemeSlug } from "@/astryx-themes";
import { Providers } from "@/components/Providers";
import { Header } from "@/components/Header";
import { Nav } from "@/components/Nav";
import { serverApi } from "@/lib/server-api";

export const metadata = { title: "Delivery Analytics" };
export const dynamic = "force-dynamic";

async function currentVersion(): Promise<string> {
  try {
    const body = (await serverApi("/api/version")) as { version: string };
    return body.version;
  } catch {
    return "";
  }
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const version = await currentVersion();
  return (
    <html lang="en">
      <body>
        <Providers version={version}>
          <Theme theme={themes[defaultThemeSlug]}>
            <AppShell sideNav={<Nav />} contentPadding={4}>
              <VStack gap={4}>
                <Header />
                {children}
              </VStack>
            </AppShell>
          </Theme>
        </Providers>
      </body>
    </html>
  );
}
