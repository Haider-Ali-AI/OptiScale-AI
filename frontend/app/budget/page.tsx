import type { Metadata } from "next";
import { BudgetStudio } from "@/components/budget";

export const metadata: Metadata = { title: "Budget decision studio" };

export default function Page() {
  return <BudgetStudio />;
}
