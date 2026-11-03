import { notFound } from "next/navigation";
import BrowsePage from "@/components/BrowsePage";
import { browseConfig, browseMetadata, browsePages } from "@/lib/browse";

export const revalidate = 21600;
export const dynamicParams = false;

interface PageProps {
  params: Promise<{ role: string }>;
}

export function generateStaticParams() {
  return browsePages("job", "role").map((page) => ({ role: page.slug }));
}

export async function generateMetadata({ params }: PageProps) {
  const { role } = await params;
  const config = browseConfig("job", "role", role);
  if (!config) notFound();
  return browseMetadata(config);
}

export default async function Page({ params }: PageProps) {
  const { role } = await params;
  const config = browseConfig("job", "role", role);
  if (!config) notFound();
  return <BrowsePage config={config} />;
}
