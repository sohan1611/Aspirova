const wordmark = "Aspirova";
const letterDelayMs = 115;

export default function BrandLoading() {
  return (
    <div className="brand-loading flex h-24 items-center justify-center">
      <span className="sr-only">Loading…</span>

      <div className="brand-loading__lockup flex items-center gap-3" aria-hidden="true">
        {/* eslint-disable-next-line @next/next/no-img-element -- tiny static brand mark; next/image is overkill here */}
        <img
          src="/logo.png"
          alt=""
          width={32}
          height={32}
          className="h-8 w-8 shrink-0 rounded-full ring-1 ring-border"
        />
        <span className="font-serif text-3xl font-semibold tracking-[-0.04em] text-foreground sm:text-4xl">
          {Array.from(wordmark).map((letter, index) => (
            <span
              key={`${letter}-${index}`}
              aria-hidden="true"
              className="brand-loading__letter"
              style={{ animationDelay: `${index * letterDelayMs}ms` }}
            >
              {letter}
            </span>
          ))}
        </span>
      </div>
    </div>
  );
}
