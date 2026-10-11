import { ArrowUpRight, LinkSimple } from "@phosphor-icons/react";
import type { Reference, Source } from "../types";

export function SourceLink({
  url,
  children,
}: {
  url: string;
  children: React.ReactNode;
}) {
  if (!/^https?:\/\//i.test(url)) return null;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer">
      {children}
      <ArrowUpRight size={14} />
    </a>
  );
}

export function Evidence({
  refs,
  sources,
}: {
  refs: Reference[];
  sources: Map<string, Source>;
}) {
  if (!refs.length) return null;
  return (
    <details className="evidence">
      <summary>
        <LinkSimple size={14} /> Source evidence ({refs.length})
      </summary>
      <div className="evidence-body">
        {refs.map((ref, index) => {
          const source = sources.get(ref.source_id);
          if (!source) return null;
          return (
            <div className="evidence-item" key={`${ref.source_id}-${index}`}>
              <blockquote>{ref.quote}</blockquote>
              <SourceLink url={source.url}>{source.title}</SourceLink>
              <span className="source-meta">
                {source.coverage === "search_excerpt"
                  ? "Search excerpt"
                  : source.coverage === "pdf"
                    ? "Text-based PDF"
                    : "Extracted page"}{" "}
                · Retrieved {new Date(source.retrieved_at).toLocaleDateString()}
              </span>
            </div>
          );
        })}
      </div>
    </details>
  );
}
