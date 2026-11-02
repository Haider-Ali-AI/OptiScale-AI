import type { Metadata } from "next";
import { Story } from "@/components/story";

export const metadata: Metadata = { title: "University story" };

export default function Page() {
  return <Story />;
}
