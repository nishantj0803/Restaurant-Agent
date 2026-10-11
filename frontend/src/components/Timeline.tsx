import { Check, MagnifyingGlass, WarningCircle } from "@phosphor-icons/react";
import type { ResearchEvent } from "../types";
import { SourceLink } from "./Evidence";

export default function Timeline({
  events,
  running,
  complete,
}: {
  events: ResearchEvent[];
  running: boolean;
  complete: boolean;
}) {
  const actions = events.filter((event) =>
    [
      "search",
      "candidate_found",
      "source_read",
      "evidence_found",
      "warning",
    ].includes(event.type),
  );
  return (
    <details className="research-log">
      <summary>
        {running ? "Researching" : complete ? "Research" : "Research so far"} ·{" "}
        {actions.filter((event) => event.type === "source_read").length} sources
      </summary>
      <div className="log-entries">
        {actions.map((event, index) => (
          <div
            className={`log-entry ${event.type === "warning" ? "log-warning" : ""}`}
            key={index}
          >
            {event.type === "search" ? (
              <MagnifyingGlass size={14} />
            ) : event.type === "warning" ? (
              <WarningCircle size={14} />
            ) : (
              <Check size={14} />
            )}
            <div>
              {event.data.source ? (
                <SourceLink url={event.data.source.url}>
                  {event.message}
                </SourceLink>
              ) : (
                <p>{event.message}</p>
              )}
              {event.data.source && (
                <small>
                  {event.data.source.coverage === "search_excerpt"
                    ? "Search excerpt"
                    : "Page read"}
                </small>
              )}
              {event.data.candidate && (
                <small>{event.data.candidate.reason}</small>
              )}
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}
