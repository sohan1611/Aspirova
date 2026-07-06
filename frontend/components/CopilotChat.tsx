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
    <main className="mx-auto w-full max-w-4xl px-4 py-12">
      <div className="mx-auto max-w-2xl text-center">
        <Badge variant="secondary">
          <Sparkles aria-hidden="true" />
          Pro
        </Badge>
        <h1 className="mt-4 text-3xl font-bold tracking-tight text-foreground">
          Career Copilot
        </h1>
        <p className="mt-2 text-muted-foreground">
          Ask focused career questions grounded in Aspirova&apos;s opportunities.
        </p>
      </div>

      <div className="mt-10">
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
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const nextTurnId = useRef(0);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ block: "nearest" });
  }, [turns, submitting]);

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
    <Card className="mx-auto w-full max-w-3xl overflow-hidden">
      <CardHeader className="border-b">
        <CardTitle className="flex items-center gap-2">
          <Bot className="size-5 text-primary" aria-hidden="true" />
          Ask Copilot
        </CardTitle>
        <CardDescription>
          Answers can help you explore, compare, and prioritize. Open each source before applying.
        </CardDescription>
      </CardHeader>

      <CardContent className="px-0">
        <Transcript
          turns={turns}
          submitting={submitting}
          endRef={transcriptEndRef}
          onSelectPrompt={setDraft}
        />
      </CardContent>

      <CardFooter className="block border-t">
        <form onSubmit={handleSubmit} className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="min-w-0 flex-1">
            <Label htmlFor="copilot-message">Message Copilot</Label>
            <Textarea
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
              className="mt-2 min-h-20 max-h-40"
            />
            <p id="copilot-message-help" className="mt-1 text-xs text-muted-foreground">
              Press Enter to send. Press Shift+Enter for a new line.
            </p>
          </div>
          <Button type="submit" disabled={submitting || rateLimited} className="w-full sm:w-auto">
            {submitting ? (
              <Loader2 className="animate-spin" aria-hidden="true" />
            ) : (
              <Send aria-hidden="true" />
            )}
            {submitting ? "Sending…" : "Send"}
          </Button>
        </form>
        {rateLimited && (
          <p className="mt-3 text-sm font-medium text-warning" role="status">
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
      className="max-h-96 min-h-80 overflow-y-auto px-6 py-5"
      role="log"
      aria-live="polite"
      aria-relevant="additions text"
      aria-label="Copilot conversation"
    >
      {turns.length === 0 ? (
        <EmptyState onSelectPrompt={onSelectPrompt} />
      ) : (
        <ol className="grid gap-4">
          {turns.map((turn) => (
            <li
              key={turn.id}
              className={cn(
                "w-fit max-w-prose rounded-xl px-4 py-3 text-sm break-words whitespace-pre-wrap",
                turn.role === "user"
                  ? "ml-auto bg-primary text-primary-foreground"
                  : "mr-auto border border-border bg-muted text-foreground",
                turn.degraded && "bg-muted/50 text-muted-foreground",
              )}
            >
              {turn.role === "assistant" && (
                <p className="mb-1 text-xs font-semibold">
                  {turn.degraded ? "Copilot unavailable" : "Copilot"}
                </p>
              )}
              <p>{turn.content}</p>
              {turn.sources && turn.sources.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2" aria-label="Sources">
                  {turn.sources.map((source) => (
                    <Badge
                      key={source.slug}
                      variant="outline"
                      asChild
                      className="h-auto max-w-full whitespace-normal py-1 text-left"
                    >
                      <Link href={`/opportunity/${source.slug}`}>
                        {source.title}
                        {source.company ? ` · ${source.company}` : ""}
                      </Link>
                    </Badge>
                  ))}
                </div>
              )}
            </li>
          ))}
          {submitting && (
            <li className="mr-auto flex items-center gap-2 rounded-xl border border-border bg-muted px-4 py-3 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              Copilot is thinking…
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
    <div className="flex min-h-72 flex-col items-center justify-center text-center">
      <MessageCircle className="size-8 text-primary" aria-hidden="true" />
      <h2 className="mt-3 font-semibold text-foreground">Start with a focused question</h2>
      <p className="mt-1 max-w-lg text-sm text-muted-foreground">
        Copilot works best when you mention the role, location, skill, or timeline you care about.
      </p>
      <div className="mt-5 grid w-full max-w-xl gap-2 sm:grid-cols-3">
        {SUGGESTED_PROMPTS.map((prompt) => (
          <Button
            key={prompt}
            type="button"
            variant="outline"
            className="h-auto whitespace-normal py-3 text-left"
            onClick={() => onSelectPrompt(prompt)}
          >
            {prompt}
          </Button>
        ))}
      </div>
    </div>
  );
}

function SignedOutCard() {
  return (
    <Card className="mx-auto max-w-xl text-center">
      <CardHeader>
        <MessageCircle className="mx-auto size-8 text-primary" aria-hidden="true" />
        <CardTitle className="text-xl">Sign in to use Career Copilot</CardTitle>
        <CardDescription>
          Use your Aspirova account to ask questions grounded in Aspirova&apos;s opportunities.
        </CardDescription>
      </CardHeader>
      <CardFooter className="justify-center">
        <HeaderAuth />
      </CardFooter>
    </Card>
  );
}

function UpsellCard() {
  return (
    <Card className="mx-auto max-w-xl text-center">
      <CardHeader>
        <Badge className="mx-auto">Pro feature</Badge>
        <CardTitle className="text-xl">Unlock your Career Copilot</CardTitle>
        <CardDescription>
          Career Copilot is included with Pro. Upgrade to ask grounded questions about your next
          opportunity and what to prioritize.
        </CardDescription>
      </CardHeader>
      <CardFooter className="justify-center">
        <Button asChild>
          <Link href="/pricing">View Pro pricing</Link>
        </Button>
      </CardFooter>
    </Card>
  );
}
