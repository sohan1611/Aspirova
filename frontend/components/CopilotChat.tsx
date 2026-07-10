"use client";

import { Bot, Loader2, MessageCircle, Send, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import HeaderAuth from "@/components/HeaderAuth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  askCopilot,
  isProFeatureRequiredError,
  isRateLimitedError,
} from "@/lib/api";
import type { CopilotSource } from "@/lib/types";
import { useSession } from "@/lib/useSession";
import { cn } from "@/lib/utils";

interface ChatTurn {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources?: CopilotSource[];
  degraded?: boolean;
}

const SUGGESTED_PROMPTS = [
  "Find remote internships I can apply to this week",
  "Which opportunities fit a frontend student?",
  "Help me prioritize my saved opportunities",
];

export default function CopilotChat() {
  const session = useSession();

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-10 sm:px-6 sm:py-14">
      <header className="mx-auto max-w-3xl">
        <div className="flex flex-wrap items-center gap-3">
          <p className="eyebrow">Career Copilot</p>
          <Badge variant="heritage">
            <Sparkles aria-hidden="true" />
            Pro intelligence
          </Badge>
        </div>
        <h1 className="mt-3 text-3xl font-semibold text-foreground sm:text-4xl">
          Turn opportunity into a plan.
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
          Ask focused career questions grounded in Aspirova&apos;s opportunity almanac, then compare
          the sources for yourself.
        </p>
      </header>

      <div className="mt-8 sm:mt-10">
        {session ? (
          <CopilotSession key={session.access_token} accessToken={session.access_token} />
        ) : (
          <SignedOutCard />
        )}
      </div>
    </main>
  );
}

function CopilotSession({ accessToken }: { accessToken: string }) {
  const [accessState, setAccessState] = useState<"pro" | "upsell">("pro");
  const [draft, setDraft] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [rateLimited, setRateLimited] = useState(false);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const nextTurnId = useRef(0);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ block: "nearest" });
  }, [turns, submitting]);

  function handleSelectPrompt(prompt: string) {
    setDraft(prompt);
    composerRef.current?.focus();
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting || rateLimited) return;

    const message = draft.trim();
    if (!message) {
      toast.error("Enter a question for Copilot.");
      return;
    }

    setTurns((current) => [
      ...current,
      { id: nextTurnId.current++, role: "user", content: message },
    ]);
    setDraft("");
    setSubmitting(true);

    try {
      const response = await askCopilot(message, accessToken);
      setTurns((current) => [
        ...current,
        {
          id: nextTurnId.current++,
          role: "assistant",
          content: response.answer,
          sources: response.sources,
          degraded: response.degraded,
        },
      ]);
    } catch (error: unknown) {
      if (isProFeatureRequiredError(error)) {
        setAccessState("upsell");
      } else if (isRateLimitedError(error)) {
        setRateLimited(true);
        toast.error("Daily Copilot limit reached", {
          description: "You've reached today's Copilot limit.",
        });
      } else {
        toast.error("Copilot couldn't answer right now. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (accessState === "upsell") return <UpsellCard />;

  return (
    <Card className="mx-auto w-full max-w-3xl gap-0 overflow-hidden shadow-soft-md">
      <CardHeader className="border-b border-border bg-secondary/25 px-5 sm:px-7">
        <div className="flex items-start gap-3">
          <span
            className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-heritage/20 bg-heritage text-heritage-foreground shadow-soft"
            aria-hidden="true"
          >
            <Bot className="size-5" />
          </span>
          <div className="min-w-0">
            <CardTitle className="font-serif text-xl leading-tight">Ask Aspirova</CardTitle>
            <CardDescription className="mt-1 leading-relaxed">
              Explore, compare, and prioritize. Open each source before applying.
            </CardDescription>
          </div>
        </div>
      </CardHeader>

      <CardContent className="px-0">
        <Transcript
          turns={turns}
          submitting={submitting}
          endRef={transcriptEndRef}
          onSelectPrompt={handleSelectPrompt}
        />
      </CardContent>

      <CardFooter className="block border-t border-border bg-card px-4 sm:px-7">
        <form onSubmit={handleSubmit} className="grid gap-3">
          <Label className="eyebrow" htmlFor="copilot-message">
            Message Copilot
          </Label>
          <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-end">
            <Textarea
              ref={composerRef}
              id="copilot-message"
              name="message"
              rows={2}
              value={draft}
              disabled={submitting || rateLimited}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder="Ask about roles, deadlines, or what to prioritize…"
              aria-describedby="copilot-message-help"
              className="min-h-24 max-h-40 min-w-0 flex-1 resize-y bg-background/60 leading-relaxed shadow-soft"
            />
            <Button
              type="submit"
              size="lg"
              disabled={submitting || rateLimited}
              className="w-full sm:w-auto"
            >
              {submitting ? (
                <Loader2 className="animate-spin" aria-hidden="true" />
              ) : (
                <Send aria-hidden="true" />
              )}
              {submitting ? "Sending…" : "Send"}
            </Button>
          </div>
          <p id="copilot-message-help" className="text-xs leading-relaxed text-muted-foreground">
            Press Enter to send. Press Shift+Enter for a new line.
          </p>
        </form>
        {rateLimited && (
          <p
            className="mt-4 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-sm font-medium text-foreground"
            role="status"
          >
            You&apos;ve reached today&apos;s Copilot limit.
          </p>
        )}
      </CardFooter>
    </Card>
  );
}

function Transcript({
  turns,
  submitting,
  endRef,
  onSelectPrompt,
}: {
  turns: ChatTurn[];
  submitting: boolean;
  endRef: React.RefObject<HTMLDivElement | null>;
  onSelectPrompt: (prompt: string) => void;
}) {
  return (
    <div
      className="max-h-96 min-h-80 overflow-y-auto bg-background/35 px-4 py-6 sm:px-7"
      role="log"
      aria-live="polite"
      aria-relevant="additions text"
      aria-label="Copilot conversation"
    >
      {turns.length === 0 ? (
        <EmptyState onSelectPrompt={onSelectPrompt} />
      ) : (
        <ol className="grid gap-5">
          {turns.map((turn) => (
            <li
              key={turn.id}
              className={cn(
                "flex items-start gap-2.5",
                turn.role === "user" ? "justify-end" : "justify-start",
              )}
            >
              {turn.role === "assistant" && (
                <span
                  className="flex size-7 shrink-0 items-center justify-center rounded-full bg-heritage font-serif text-xs font-semibold text-heritage-foreground shadow-soft"
                  aria-hidden="true"
                >
                  A
                </span>
              )}
              <div
                className={cn(
                  "w-fit min-w-0 max-w-prose rounded-xl border px-4 py-3 text-sm leading-relaxed",
                  turn.role === "user"
                    ? "border-primary/20 bg-primary/10 text-foreground"
                    : "border-border bg-card text-card-foreground shadow-soft",
                  turn.degraded && "bg-muted/40 text-muted-foreground shadow-none",
                )}
              >
                {turn.role === "assistant" && (
                  <p className="eyebrow mb-2">
                    {turn.degraded ? "Copilot unavailable" : "Copilot"}
                  </p>
                )}
                <p className="break-words whitespace-pre-wrap">{turn.content}</p>
                {turn.sources && turn.sources.length > 0 && (
                  <div className="mt-4 border-t border-border pt-3" aria-label="Sources">
                    <p className="eyebrow mb-2">Sources</p>
                    <div className="flex min-w-0 flex-wrap gap-2">
                      {turn.sources.map((source) => (
                        <Badge
                          key={source.slug}
                          variant="outline"
                          asChild
                          className="h-auto max-w-full justify-start whitespace-normal border-primary/20 bg-background/70 px-2.5 py-1.5 text-left normal-case tracking-normal text-muted-foreground hover:border-primary/45 hover:text-foreground"
                        >
                          <Link className="break-words" href={`/opportunity/${source.slug}`}>
                            {source.title}
                            {source.company ? ` · ${source.company}` : ""}
                          </Link>
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </li>
          ))}
          {submitting && (
            <li className="flex items-start gap-2.5">
              <span
                className="flex size-7 shrink-0 items-center justify-center rounded-full bg-heritage font-serif text-xs font-semibold text-heritage-foreground shadow-soft"
                aria-hidden="true"
              >
                A
              </span>
              <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground shadow-soft">
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                Copilot is thinking…
              </div>
            </li>
          )}
        </ol>
      )}
      <div ref={endRef} />
    </div>
  );
}

function EmptyState({ onSelectPrompt }: { onSelectPrompt: (prompt: string) => void }) {
  return (
    <div className="flex min-h-72 flex-col items-center justify-center rounded-xl border border-border bg-secondary/25 px-4 py-8 text-center sm:px-6">
      <span className="flex size-12 items-center justify-center rounded-xl border border-primary/20 bg-card text-primary shadow-soft">
        <MessageCircle className="size-6" aria-hidden="true" />
      </span>
      <p className="eyebrow mt-5">Begin with a question</p>
      <h2 className="mt-2 text-xl font-semibold text-foreground">What would make the search clearer?</h2>
      <p className="mt-2 max-w-lg text-sm leading-relaxed text-muted-foreground">
        Copilot works best when you mention the role, location, skill, or timeline you care about.
      </p>
      <div className="mt-6 grid w-full max-w-2xl gap-2.5 sm:grid-cols-3">
        {SUGGESTED_PROMPTS.map((prompt, index) => (
          <Button
            key={prompt}
            type="button"
            variant="outline"
            className="h-auto min-w-0 justify-start gap-3 whitespace-normal border-border bg-card px-3 py-3 text-left leading-snug shadow-soft hover:border-primary/45 hover:bg-secondary/50"
            onClick={() => onSelectPrompt(prompt)}
          >
            <span className="tnum flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs text-primary">
              {String(index + 1).padStart(2, "0")}
            </span>
            <span className="min-w-0">{prompt}</span>
          </Button>
        ))}
      </div>
    </div>
  );
}

function SignedOutCard() {
  return (
    <Card className="mx-auto max-w-2xl overflow-hidden shadow-soft-md">
      <CardHeader className="justify-items-center px-5 text-center sm:px-10">
        <span className="flex size-12 items-center justify-center rounded-xl border border-primary/20 bg-secondary/50 text-primary shadow-soft">
          <MessageCircle className="size-6" aria-hidden="true" />
        </span>
        <p className="eyebrow mt-3">Member access</p>
        <CardTitle className="font-serif text-2xl leading-tight">
          Sign in to start a conversation
        </CardTitle>
        <CardDescription className="max-w-lg leading-relaxed">
          Use your Aspirova account to ask questions grounded in Aspirova&apos;s opportunities.
        </CardDescription>
      </CardHeader>
      <CardFooter className="justify-center px-5 sm:px-10">
        <HeaderAuth
          triggerLabel="Sign in to continue"
          triggerSize="lg"
          triggerClassName="w-full sm:w-auto"
        />
      </CardFooter>
    </Card>
  );
}

function UpsellCard() {
  return (
    <Card className="mx-auto max-w-2xl overflow-hidden border-heritage/20 shadow-soft-md">
      <CardHeader className="justify-items-center px-5 text-center sm:px-10">
        <span className="flex size-12 items-center justify-center rounded-xl bg-heritage text-heritage-foreground shadow-soft">
          <Sparkles className="size-6" aria-hidden="true" />
        </span>
        <p className="eyebrow mt-3">Pro access</p>
        <CardTitle className="font-serif text-2xl leading-tight">
          Unlock your Career Copilot
        </CardTitle>
        <CardDescription className="max-w-lg leading-relaxed">
          Career Copilot is included with Pro. Upgrade to ask grounded questions about your next
          opportunity and what to prioritize.
        </CardDescription>
      </CardHeader>
      <CardFooter className="justify-center px-5 sm:px-10">
        <Button asChild size="lg" className="w-full sm:w-auto">
          <Link href="/pricing">View Pro pricing</Link>
        </Button>
      </CardFooter>
    </Card>
  );
}
