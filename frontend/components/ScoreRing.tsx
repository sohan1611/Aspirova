export default function ScoreRing({ score, size = "lg" }: { score: number; size?: "lg" | "sm" }) {
  const progress = Math.min(100, Math.max(0, score));
  const circumference = 2 * Math.PI * 52;
  return (
    <div className={size === "sm" ? "relative mx-auto size-16" : "relative mx-auto size-40"} role="img" aria-label={`ATS readiness estimate: ${score} out of 100`}>
      <svg viewBox="0 0 128 128" className="size-full -rotate-90" aria-hidden="true">
        <circle cx="64" cy="64" r="52" fill="none" strokeWidth="9" className="stroke-muted" />
        <circle cx="64" cy="64" r="52" fill="none" strokeWidth="9" strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={circumference * (1 - progress / 100)} className={score >= 75 ? "stroke-success" : score >= 50 ? "stroke-primary" : "stroke-warning"} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center" aria-hidden="true">
        <span className={size === "sm" ? "font-serif text-lg font-bold" : "font-serif text-4xl font-bold"}>{score}</span>
        {size === "lg" && <span className="text-sm text-muted-foreground">/ 100</span>}
      </div>
    </div>
  );
}
