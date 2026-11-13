import { useState } from "react";
import type { Campaign, ConsistencyReport } from "../api";
import { api } from "../api";
import { ganttBars } from "../plan";

export function Gantt({ campaign }: { campaign: Campaign }) {
  const bars = ganttBars(campaign);
  const vessels = campaign.vessels.map((v) => v.name);
  return (
    <div className="gantt" aria-label="Schedule">
      {vessels.map((name) => (
        <div className="lane" key={name}>
          <div className="lane-label">{name}</div>
          <div className="lane-track">
            {bars
              .filter((b) => b.vessel === name)
              .map((b) => (
                <div
                  key={b.taskId}
                  className="bar"
                  style={{ left: `${b.offsetPct}%`, width: `${b.widthPct}%` }}
                  title={`${b.label}: +${b.startHour}h to +${b.endHour}h`}
                >
                  {b.label}
                </div>
              ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function CampaignView({
  campaign,
  onChanged,
  onDeleted,
}: {
  campaign: Campaign;
  onChanged: (c: Campaign) => void;
  onDeleted: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [tags, setTags] = useState("");
  const [error, setError] = useState("");
  const [report, setReport] = useState<ConsistencyReport | null>(null);
  const [busy, setBusy] = useState(false);
  const task = new Map(campaign.tasks.map((t) => [t.id, t]));
  const vessel = new Map(campaign.vessels.map((v) => [v.id, v]));

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      await api.uploadDocument(campaign.id, file, title, tags);
      setFile(null);
      setTitle("");
      setTags("");
      onChanged(await api.getCampaign(campaign.id));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function check() {
    setBusy(true);
    setError("");
    try {
      setReport(await api.consistency(campaign.id));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete ${campaign.name} from all four stores?`)) return;
    await api.deleteCampaign(campaign.id);
    onDeleted();
  }

  return (
    <section className="card">
      <h2>
        {campaign.name} {campaign.synthetic && <span className="badge">SYNTHETIC</span>}
      </h2>
      <p>{campaign.objective}</p>
      <p>
        Start {campaign.start_time} UTC, makespan {campaign.makespan_hours} h, {campaign.vessels.length} vessels,{" "}
        {campaign.tasks.length} tasks.
      </p>

      <h3>Schedule</h3>
      <Gantt campaign={campaign} />
      <table>
        <thead>
          <tr><th>Task</th><th>Kind</th><th>Vessel</th><th>Start</th><th>End</th><th>After</th></tr>
        </thead>
        <tbody>
          {campaign.schedule.map((s) => {
            const t = task.get(s.task_id);
            return (
              <tr key={s.task_id}>
                <td>{t?.name}</td>
                <td>{t?.kind}</td>
                <td>{vessel.get(s.vessel_id)?.name}</td>
                <td>{s.start}</td>
                <td>{s.end}</td>
                <td>{t?.depends_on.map((d) => task.get(d)?.name).join(", ")}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h3>Documents (MinIO, indexed in OpenSearch)</h3>
      <ul>
        {campaign.documents.map((d) => (
          <li key={d.id}>
            <a href={`/api/documents/${d.id}/content`}>{d.title}</a> ({d.filename}, {d.size_bytes} bytes,{" "}
            {d.tags.join(", ")}) <code>{d.sha256.slice(0, 12)}</code>
          </li>
        ))}
      </ul>
      <form onSubmit={upload} aria-label="Attach document">
        <input aria-label="document file" type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <input aria-label="document title" placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
        <input aria-label="document tags" placeholder="tags, comma separated" value={tags} onChange={(e) => setTags(e.target.value)} />
        <button type="submit" disabled={!file || busy}>Attach</button>
      </form>

      <h3>Cross-service consistency</h3>
      <button onClick={check} disabled={busy}>Check Postgres / MinIO / OpenSearch / Fuseki</button>
      {report && (
        <div>
          <p>
            {report.passed} passed, {report.failed} failed
          </p>
          <ul className="checks">
            {report.checks.map((c, i) => (
              <li key={i} className={c.ok ? "ok" : "fail"}>
                [{c.ok ? "PASS" : "FAIL"}] {c.service}: {c.name} {c.detail && `(${c.detail})`}
              </li>
            ))}
          </ul>
        </div>
      )}
      {error && <p role="alert" className="errors">{error}</p>}
      <button className="danger" onClick={remove}>Delete campaign</button>
    </section>
  );
}
