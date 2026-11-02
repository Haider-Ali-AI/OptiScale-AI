import type { Metadata } from "next";
import { Commerce } from "@/components/commerce";

export const metadata: Metadata = { title: "Commerce & attribution" };

export default function Page() {
  return <Commerce />;
}
