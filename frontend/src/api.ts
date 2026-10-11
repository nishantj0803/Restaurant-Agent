import type { ResearchEvent } from "./types";

export async function research(
  message: string,
  answers: string[],
  signal: AbortSignal,
  onEvent: (event: ResearchEvent) => void,
  sessionId?: string,
) {
  const response = await fetch("/api/recommendations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      clarification_answers: answers,
      session_id: sessionId ?? null,
    }),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(
      "The research service could not accept this request. Check that the backend is running.",
    );
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal = false;
  const consume = (line: string) => {
    if (!line.trim()) return;
    const event = JSON.parse(line) as ResearchEvent;
    if (["result", "answer", "error", "clarification"].includes(event.type))
      terminal = true;
    onEvent(event);
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      lines.forEach(consume);
    }
    buffer += decoder.decode();
    consume(buffer);
    if (!terminal)
      throw new Error(
        "The connection ended before research finished. Please retry.",
      );
  } finally {
    reader.releaseLock();
  }
}
