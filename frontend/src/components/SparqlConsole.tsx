import { useState } from "react";
import { api } from "../api";
import { SAMPLE_QUERIES, sparqlTable } from "../plan";

const FIRST = Object.keys(SAMPLE_QUERIES)[0];

export function SparqlConsole({ run = api.sparql }: { run?: typeof api.sparql }) {
  const [query, setQuery] = useState(SAMPLE_QUERIES[FIRST]);
  const [table, setTable] = useState<{ columns: string[]; rows: string[][] } | null>(null);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setTable(null);
    try {
      setTable(sparqlTable(await run(query)));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section className="card">
      <h2>Ontology layer (SPARQL on Fuseki)</h2>
      <p className="note">
        Read-only SELECT and ASK queries over the RDF mirror of every campaign and the checked-in ontology (
        <a href="/api/ontology">mcw.ttl</a>).
      </p>
      <label>
        Example
        <select aria-label="example query" onChange={(e) => setQuery(SAMPLE_QUERIES[e.target.value])}>
          {Object.keys(SAMPLE_QUERIES).map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
      </label>
      <form onSubmit={submit}>
        <textarea aria-label="sparql query" rows={8} value={query} onChange={(e) => setQuery(e.target.value)} />
        <button type="submit">Run query</button>
      </form>
      {error && <p role="alert" className="errors">{error}</p>}
      {table && (
        <table aria-label="sparql results">
          <thead>
            <tr>{table.columns.map((c) => <th key={c}>{c}</th>)}</tr>
          </thead>
          <tbody>
            {table.rows.map((r, i) => (
              <tr key={i}>{r.map((v, j) => <td key={j}>{v}</td>)}</tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
