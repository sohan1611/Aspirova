import type { Metadata } from "next";
import { Fraunces, Geist, Geist_Mono } from "next/font/google";
import { Suspense } from "react";
import AppFooter from "@/components/AppFooter";
import AppHeader from "@/components/AppHeader";
import { BookmarksProvider } from "@/components/BookmarksProvider";
import OnboardingDialog from "@/components/OnboardingDialog";
import ReferralCapture from "@/components/ReferralCapture";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  display: "swap",
});

const SITE_URL = "https://www.aspirova.org";
const TITLE = "Aspirova - Every opportunity. One place.";
const DESCRIPTION =
  "AI-powered career intelligence for students. Aspirova discovers internships, jobs, and hidden opportunities from across the web and brings them to one place.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: TITLE, template: "%s - Aspirova" },
  description: DESCRIPTION,
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "website",
    url: SITE_URL,
    siteName: "Aspirova",
    locale: "en_US",
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} ${fraunces.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col">
        <ThemeProvider attribute="class" forcedTheme="light" disableTransitionOnChange>
          <a
            href="#main-content"
            className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[100] focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-primary-foreground focus:shadow-soft focus:outline-none focus:ring-2 focus:ring-ring"
          >
            Skip to content
          </a>
          <Suspense fallback={null}>
            <ReferralCapture />
          </Suspense>
          <BookmarksProvider>
            <AppHeader />
            <div id="main-content" tabIndex={-1} className="flex-1">
              {children}
            </div>
            <Suspense fallback={null}>
              <OnboardingDialog />
            </Suspense>
          </BookmarksProvider>
          <AppFooter />
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
