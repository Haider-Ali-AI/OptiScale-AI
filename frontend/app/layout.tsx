import type { Metadata, Viewport } from "next";
import "@fontsource/manrope/400.css";
import "@fontsource/manrope/500.css";
import "@fontsource/manrope/600.css";
import "@fontsource/manrope/700.css";
import "@fontsource/manrope/800.css";
import "@fontsource/ibm-plex-mono/400.css";
import "./globals.css";
import { Shell } from "@/components/shell";

export const metadata: Metadata = {
  title: { default: "SignalSpend AI", template: "%s · SignalSpend AI" },
  description:
    "Marketing intelligence and advisory budget optimization: weighted KPIs, Big Data engine comparison, validated ML and exact PKR allocations.",
  icons: { icon: "/icon.svg" },
};
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

// Applied before paint so a stored theme never flashes the wrong palette.
const themeScript = `try{var t=localStorage.getItem("signalspend.theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <a href="#main" className="sr-only">
          Skip to content
        </a>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
