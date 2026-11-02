import type { Metadata } from "next";
import { DataStudio } from "@/components/data-studio";

export const metadata: Metadata = { title: "Data studio" };

export default function Page() {
  return <DataStudio />;
}
