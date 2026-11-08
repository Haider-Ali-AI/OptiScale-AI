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
  title: { default: "OptiScale AI", template: "%s · OptiScale AI" },
  description:
    "Scalable Marketing Intelligence & Cross-Channel Optimization Engine: weighted KPIs, Big Data engine benchmarks, validated XGBoost revenue modeling, and exact PKR budget allocation.",
  icons: { icon: "/icon.svg" },
};
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

// Applied before paint so a stored theme never flashes the wrong palette.
const themeScript = `try{var t=localStorage.getItem("optiscale.theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

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
