import type { Metadata } from "next";
import { Assistant } from "@/components/assistant";

export const metadata: Metadata = { title: "AI insight assistant" };

export default function Page() {
  return <Assistant />;
}
