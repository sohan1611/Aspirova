import type { MetadataRoute } from "next";

export const revalidate = 86400;

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Aspirova",
    short_name: "Aspirova",
    description: "Internships, jobs, hackathons and research programmes for students, gathered daily from company career pages and public sources. Always links to the original listing.",
    start_url: "/",
    display: "standalone",
    background_color: "#f7f8fb",
    theme_color: "#ffffff",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
