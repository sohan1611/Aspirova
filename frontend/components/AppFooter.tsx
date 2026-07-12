import Link from "next/link";
import Wordmark from "@/components/Wordmark";

export default function AppFooter() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto max-w-[1680px] px-4 py-12 sm:px-6 lg:px-10 lg:py-14 xl:px-12">
        <div className="grid gap-10 md:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_1fr_1fr] lg:gap-12">
          <div>
            <Wordmark />
            <p className="mt-4 max-w-xl text-sm leading-relaxed text-muted-foreground">
              Aspirova indexes opportunities directly from company career pages and links
              every application to its original source.
            </p>
          </div>

          <nav aria-label="Browse opportunities">
            <p className="eyebrow">Browse</p>
            <ul className="mt-4 space-y-3 text-sm">
              <li>
                <Link className="text-muted-foreground hover:text-foreground" href="/internships">
                  Internships
                </Link>
              </li>
              <li>
                <Link className="text-muted-foreground hover:text-foreground" href="/jobs">
                  Jobs
                </Link>
              </li>
              <li>
                <Link className="text-muted-foreground hover:text-foreground" href="/remote">
                  Remote
                </Link>
              </li>
              <li>
                <Link className="text-muted-foreground hover:text-foreground" href="/competitions">
                  Competitions
                </Link>
              </li>
              <li>
                <Link className="text-muted-foreground hover:text-foreground" href="/research">
                  Research
                </Link>
              </li>
              <li>
                <Link className="text-muted-foreground hover:text-foreground" href="/companies">
                  Companies
                </Link>
              </li>
            </ul>
          </nav>

          <nav aria-label="Aspirova">
            <p className="eyebrow">Aspirova</p>
            <ul className="mt-4 space-y-3 text-sm">
              <li>
                <Link className="text-muted-foreground hover:text-foreground" href="/pricing">
                  Pricing
                </Link>
              </li>
              <li>
                <Link className="text-muted-foreground hover:text-foreground" href="/referral">
                  Invite
                </Link>
              </li>
              <li>
                <Link className="text-muted-foreground hover:text-foreground" href="/copilot">
                  Copilot
                </Link>
              </li>
              <li>
                <Link className="text-muted-foreground hover:text-foreground" href="/resume">
                  Matches
                </Link>
              </li>
            </ul>
          </nav>
        </div>

        <p className="mt-10 border-t border-border pt-5 text-xs leading-relaxed text-muted-foreground">
          Source-first, always: every opportunity is indexed from a company career page,
          and every Apply link takes you back to the company.
        </p>

        <div className="mt-5 flex flex-col gap-3 border-t border-border pt-5 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-muted-foreground">
            © {new Date().getFullYear()} Aspirova · Built by a student, for students.
          </p>
          <p className="eyebrow">Est. 2026</p>
        </div>
      </div>
    </footer>
  );
}
