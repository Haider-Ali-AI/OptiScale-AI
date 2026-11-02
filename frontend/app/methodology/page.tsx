import type { Metadata } from "next";
import { Methodology } from "@/components/methodology";

export const metadata: Metadata = { title: "Methodology & help" };

export default function Page() {
  return <Methodology />;
}
