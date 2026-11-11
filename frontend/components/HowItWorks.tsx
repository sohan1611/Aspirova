import Link from "next/link";
import HowItWorksDismiss from "@/components/HowItWorksDismiss";

const steps = [
  ["Browse", "Listings gathered from public sources."],
  ["Check eligibility", "On the listing."],
  ["Apply on the original site", "The employer’s or organiser’s own page."],
  ["Track", "Save it and mark your progress in Saved."],
];

function Notes() {
  return (
    <div className="space-y-1 text-xs leading-4 text-muted-foreground">
      <p>For You uses the field and interests you choose.</p>
      <p>&apos;Posted&apos; is the source&apos;s date; &apos;Seen&apos; is when we last found it.</p>
      <p>Follow a company to get an email when it posts roles.</p>
    </div>
  );
}

export default function HowItWorks() {
  return (
    <section
      data-how-it-works
      aria-labelledby="how-it-works-title"
      className="mt-4 max-w-4xl rounded-md border border-border bg-muted px-2 py-1.5 sm:mt-6 sm:p-4"
    >
      <div className="flex items-center gap-2">
        <h2 id="how-it-works-title" className="mr-auto text-sm leading-5">
          How Aspirova works
        </h2>
        <HowItWorksDismiss />
        <HowItWorksDismiss icon />
      </div>
      <ol role="list" className="mt-1 flex flex-wrap gap-x-1 text-xs leading-4 sm:mt-3 sm:grid sm:grid-cols-4 sm:gap-4 sm:text-sm sm:leading-5">
        {steps.map(([title, description], index) => (
          <li key={title}>
            {index > 0 && <span aria-hidden="true" className="mr-1 sm:hidden">→</span>}
            <span className="font-semibold">{title}</span>
            <span className="sr-only sm:not-sr-only sm:mt-1 sm:block sm:text-xs sm:leading-4 sm:text-muted-foreground">
              {" "}{description}
            </span>
          </li>
        ))}
      </ol>
      <details className="mt-1 text-xs leading-4 sm:hidden">
        <summary className="cursor-pointer rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
          How recommendations and alerts work
        </summary>
        <div className="py-2"><Notes /></div>
      </details>
      <div className="mt-3 hidden sm:block"><Notes /></div>
      <div className="mt-1 flex gap-3 text-xs leading-5 text-primary sm:mt-3">
        <Link href="/faq" className="rounded underline underline-offset-2">FAQ</Link>
        <Link href="/about" className="rounded underline underline-offset-2">How we find listings</Link>
      </div>
    </section>
  );
}
