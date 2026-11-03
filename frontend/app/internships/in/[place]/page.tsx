import { notFound } from "next/navigation";
import BrowsePage from "@/components/BrowsePage";
import { browseConfig, browseMetadata, browsePages } from "@/lib/browse";

export const revalidate = 21600;
export const dynamicParams = false;

interface PageProps {
  params: Promise<{ place: string }>;
}

export function generateStaticParams() {
  return browsePages("internship", "place").map((page) => ({ place: page.slug }));
}

export async function generateMetadata({ params }: PageProps) {
  const { place } = await params;
  const config = browseConfig("internship", "place", place);
  if (!config) notFound();
  return browseMetadata(config);
}

export default async function Page({ params }: PageProps) {
  const { place } = await params;
  const config = browseConfig("internship", "place", place);
  if (!config) notFound();
  return <BrowsePage config={config} />;
}
