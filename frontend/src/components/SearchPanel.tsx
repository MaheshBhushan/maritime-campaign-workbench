import { useState } from "react";
import type { SearchHit } from "../api";
import { api } from "../api";

export function SearchPanel({ search = api.search }: { search?: typeof api.search }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [error, setError] = useState("");

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      setHits(await search(q));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section className="card">
      <h2>Document search (OpenSearch)</h2>
      <form onSubmit={run}>
        <input aria-label="search query" value={q} onChange={(e) => setQ(e.target.value)} placeholder="title, tag or text" />
        <button type="submit">Search</button>
      </form>
      {error && <p role="alert" className="errors">{error}</p>}
      {hits && (
        <ul aria-label="search results">
          {hits.length === 0 && <li>No documents found.</li>}
          {hits.map((h) => (
            <li key={h.document_id}>
              <a href={`/api/documents/${h.document_id}/content`}>{h.title}</a> in {h.campaign_name} [
              {h.tags.join(", ")}]{h.highlight && <div className="highlight" dangerouslySetInnerHTML={{ __html: escapeExceptEm(h.highlight) }} />}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** OpenSearch wraps matches in <em>; keep those, escape everything else. */
export function escapeExceptEm(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/&lt;(\/?)em&gt;/g, "<$1em>");
}
