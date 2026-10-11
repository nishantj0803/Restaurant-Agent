import { useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  ForkKnife,
  Plus,
  Stop,
  WarningCircle,
} from "@phosphor-icons/react";
import { research } from "./api";
import { Evidence } from "./components/Evidence";
import RecommendationCard from "./components/RecommendationCard";
import Timeline from "./components/Timeline";
import type { Preferences, ResearchEvent, Result, Source } from "./types";

interface Turn {
  id: number;
  role: "user" | "assistant";
  text: string;
  events: ResearchEvent[];
  result?: Result;
  preferences?: Preferences;
  error?: boolean;
}

export default function App() {
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [running, setRunning] = useState(false);
  const [health, setHealth] = useState<{
    status: string;
    missing_keys: string[];
  } | null>(null);
  const [sessionId, setSessionId] = useState<string>();
  const [pendingQuestion, setPendingQuestion] = useState("");
  const controller = useRef<AbortController | null>(null);
  const counter = useRef(0);
  const input = useRef<HTMLTextAreaElement>(null);
  const anchor = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const request = new AbortController();
    fetch("/api/health", { signal: request.signal })
      .then((response) => response.json())
      .then(setHealth)
      .catch(() => {});
    return () => {
      request.abort();
      controller.current?.abort();
    };
  }, []);

  function updateTurn(id: number, update: (turn: Turn) => Turn) {
    setTurns((previous) =>
      previous.map((turn) => (turn.id === id ? update(turn) : turn)),
    );
  }

  async function send() {
    const text = message.trim();
    if (!text || running) return;
    const assistantId = ++counter.current;
    const userId = ++counter.current;
    const request = new AbortController();
    controller.current = request;
    setTurns((previous) => [
      ...previous,
      { id: userId, role: "user", text, events: [] },
      { id: assistantId, role: "assistant", text: "", events: [] },
    ]);
    setMessage("");
    setRunning(true);
    setPendingQuestion("");
    let hasTextReply = false;
    setTimeout(
      () =>
        anchor.current?.scrollIntoView({ block: "end", behavior: "smooth" }),
      50,
    );
    try {
      await research(
        text,
        [],
        request.signal,
        (event) => {
          if (["answer", "clarification", "error"].includes(event.type))
            hasTextReply = true;
          if (event.type === "session") setSessionId(event.data.session_id);
          updateTurn(assistantId, (turn) => {
            const next = { ...turn, events: [...turn.events, event] };
            if (event.type === "preferences")
              next.preferences = event.data.preferences;
            if (
              event.type === "answer" ||
              event.type === "clarification" ||
              event.type === "error"
            )
              next.text = event.message;
            if (event.type === "error") next.error = true;
            if (event.type === "result") {
              next.result = event.data.result;
              next.preferences = event.data.result?.preferences;
            }
            return next;
          });
          if (event.type === "clarification") setPendingQuestion(event.message);
        },
        sessionId,
      );
    } catch (error) {
      if (!request.signal.aborted)
        updateTurn(assistantId, (turn) => ({
          ...turn,
          error: true,
          text:
            error instanceof Error
              ? error.message
              : "The connection failed. Please try again.",
        }));
    } finally {
      setRunning(false);
      requestAnimationFrame(() => {
        input.current?.focus({ preventScroll: true });
        if (hasTextReply)
          anchor.current?.scrollIntoView({ block: "end", behavior: "smooth" });
      });
    }
  }

  function stop() {
    controller.current?.abort();
    setTurns((previous) =>
      previous.map((turn, index) =>
        index === previous.length - 1
          ? {
              ...turn,
              text: "Stopped. You can change your request and try again.",
            }
          : turn,
      ),
    );
  }

  function newChat() {
    if (running) return;
    setTurns([]);
    setSessionId(undefined);
    setMessage("");
    setPendingQuestion("");
    input.current?.focus();
  }

  return (
    <div className="chat-app">
      <a className="skip-link" href="#message-input">
        Skip to message
      </a>
      <header className="chat-header">
        <button className="brand" onClick={newChat} aria-label="Tablefind home">
          <ForkKnife size={22} weight="bold" />
          <span>Tablefind</span>
        </button>
        <button className="new-chat" onClick={newChat} disabled={running}>
          <Plus size={17} />
          New chat
        </button>
      </header>
      <main className="chat-main">
        {health?.status === "configuration_required" && (
          <div className="setup-notice" role="alert">
            <WarningCircle size={18} />
            <p>
              Configure {health.missing_keys.join(" and ")} in .env and restart
              the backend.
            </p>
          </div>
        )}
        {!turns.length && (
          <section className="welcome">
            <h1>Where are you eating?</h1>
          </section>
        )}
        <div className="conversation" aria-label="Conversation">
          {turns.map((turn, index) => {
            if (turn.role === "user")
              return (
                <div className="user-turn" key={turn.id}>
                  <p>{turn.text}</p>
                </div>
              );
            const isRunning = running && index === turns.length - 1;
            const result = turn.result;
            const answer = turn.events.find((event) => event.type === "answer");
            const sources = new Map<string, Source>(
              (
                result?.sources ??
                answer?.data.sources ??
                turn.events.flatMap((event) =>
                  event.data.source ? [event.data.source] : [],
                )
              ).map((source) => [source.id, source]),
            );
            const preferences = turn.preferences;
            const stage = [...turn.events]
              .reverse()
              .find((event) => event.type === "stage_started")?.message;
            return (
              <article
                className={`assistant-turn ${turn.error ? "turn-error" : ""}`}
                key={turn.id}
              >
                <div className="assistant-byline">
                  <ForkKnife size={16} />
                  <span>Tablefind</span>
                </div>
                {isRunning && (
                  <p className="working-message" role="status">
                    {stage ?? "Starting…"}
                  </p>
                )}
                {turn.text && (
                  <p
                    className="assistant-text"
                    role={turn.error ? "alert" : undefined}
                  >
                    {turn.text}
                  </p>
                )}
                {answer?.data.refs && (
                  <Evidence refs={answer.data.refs} sources={sources} />
                )}
                {turn.events.some((event) => event.type === "search") && (
                  <Timeline
                    events={turn.events}
                    running={isRunning}
                    complete={!!result}
                  />
                )}
                {result && (
                  <>
                    <div className="results-summary">
                      <h2>
                        {result.recommendations.length
                          ? `${result.recommendations.length} ${result.recommendations.length === 1 ? "option" : "options"} in ${result.preferences.city}`
                          : `I couldn't find a good match in ${result.preferences.city}`}
                      </h2>
                      <span>
                        {Math.round(result.usage.elapsed_seconds)}s ·{" "}
                        {result.sources.length} sources
                      </span>
                    </div>
                    {preferences && (
                      <p className="search-context">
                        {[
                          preferences.meal !== "any" ? preferences.meal : "",
                          preferences.budget
                            ? `${preferences.budget_operator === "lt" ? "Under" : "Up to"} ${preferences.currency === "EUR" ? "€" : preferences.currency + " "}${preferences.budget}`
                            : "",
                          preferences.vegetarian ? "Vegetarian" : "",
                          ...preferences.excluded_ingredients.map(
                            (ingredient) => `No ${ingredient}`,
                          ),
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                    )}
                    {result.recommendations.map((item, index) => (
                      <RecommendationCard
                        key={item.website + item.name}
                        item={item}
                        index={index}
                        sources={sources}
                      />
                    ))}
                    {!result.recommendations.length && (
                      <p className="assistant-text">
                        The sources were incomplete or the options did not fit.
                        We can try a different neighbourhood or budget.
                      </p>
                    )}
                    <details className="run-notes">
                      <summary>Search notes</summary>
                      {result.preferences.assumptions.length > 0 && (
                        <ul>
                          {result.preferences.assumptions.map((note, index) => (
                            <li key={index}>{note}</li>
                          ))}
                        </ul>
                      )}
                      {result.warnings.length > 0 && (
                        <ul>
                          {result.warnings.map((note, index) => (
                            <li key={index}>{note}</li>
                          ))}
                        </ul>
                      )}
                    </details>
                    {result.excluded.length > 0 && (
                      <details className="excluded-places">
                        <summary>
                          Other places checked ({result.excluded.length})
                        </summary>
                        {result.excluded.map((item, index) => (
                          <RecommendationCard
                            key={item.website + item.name}
                            item={item}
                            index={index}
                            sources={sources}
                          />
                        ))}
                      </details>
                    )}
                  </>
                )}
              </article>
            );
          })}
        </div>
        <div ref={anchor} className="conversation-end" />
      </main>
      <div className="composer-area">
        <form
          className="composer"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <label className="sr-only" htmlFor="message-input">
            Message Tablefind
          </label>
          <textarea
            id="message-input"
            ref={input}
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder={
              pendingQuestion
                ? "Your answer…"
                : turns.length
                  ? "Ask a follow-up or change your plans…"
                  : "Find a place to eat…"
            }
            rows={2}
            maxLength={4000}
            disabled={running}
            onKeyDown={(event) => {
              if (
                event.key === "Enter" &&
                !event.shiftKey &&
                !event.nativeEvent.isComposing
              ) {
                event.preventDefault();
                void send();
              }
            }}
          />
          <div className="composer-bottom">
            {running ? (
              <button type="button" onClick={stop} aria-label="Stop research">
                <Stop size={17} weight="fill" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!message.trim()}
                aria-label="Send message"
              >
                <ArrowUp size={19} weight="bold" />
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
