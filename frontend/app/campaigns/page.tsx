import type { Metadata } from "next";
import { Campaigns } from "@/components/campaigns";

export const metadata: Metadata = { title: "Campaign explorer" };

export default function Page() {
  return <Campaigns />;
}
