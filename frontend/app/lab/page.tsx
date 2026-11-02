import type { Metadata } from "next";
import { BigDataLab } from "@/components/lab";

export const metadata: Metadata = { title: "Big Data lab" };

export default function Page() {
  return <BigDataLab />;
}
