import Wordmark from "@/components/Wordmark";

export default function AppFooter() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto max-w-4xl px-4 py-10">
        <Wordmark />
        <p className="mt-3 max-w-xl text-sm text-muted-foreground">
          Every opportunity. One place. Aspirova crawls company career pages
          directly - Greenhouse, Lever, Ashby, and more - and always links out
          to the original source. We never mirror an application; every
          &ldquo;Apply&rdquo; takes you straight to the company.
        </p>
        <p className="mt-6 text-xs text-muted-foreground">
          © {new Date().getFullYear()} Aspirova. Built by a student, for students.
        </p>
      </div>
    </footer>
  );
}
