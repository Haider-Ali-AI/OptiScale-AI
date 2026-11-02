import type { Metadata } from "next";
import { ModelStudio } from "@/components/models";

export const metadata: Metadata = { title: "ML validation studio" };

export default function Page() {
  return <ModelStudio />;
}
