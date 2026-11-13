import { useState } from "react";
import type { Campaign } from "../api";
import { api } from "../api";
import { toPayload, type CampaignForm, type TaskRow, type VesselRow } from "../plan";

const emptyVessel = (n: number): VesselRow => ({
  key: `v${n}`,
  name: "",
  vessel_class: "",
  home_port: "",
  turnaround_hours: "0",
});
const emptyTask = (n: number, vessel: string): TaskRow => ({
  key: `t${n}`,
  name: "",
  kind: "",
  duration_hours: "1",
  vessel,
  depends_on: "",
});

export function CampaignFormView({
  onCreated,
  create = api.createCampaign,
}: {
  onCreated: (c: Campaign) => void;
  create?: typeof api.createCampaign;
}) {
  const [form, setForm] = useState<CampaignForm>({
    name: "",
    objective: "",
    start_local: "",
    vessels: [emptyVessel(1)],
    tasks: [emptyTask(1, "v1")],
  });
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const setVessel = (i: number, patch: Partial<VesselRow>) =>
    setForm((f) => ({ ...f, vessels: f.vessels.map((v, j) => (j === i ? { ...v, ...patch } : v)) }));
  const setTask = (i: number, patch: Partial<TaskRow>) =>
    setForm((f) => ({ ...f, tasks: f.tasks.map((t, j) => (j === i ? { ...t, ...patch } : t)) }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const { payload, errors: problems } = toPayload(form);
    setErrors(problems);
    if (!payload) return;
    setBusy(true);
    try {
      onCreated(await create(payload));
    } catch (err) {
      setErrors([(err as Error).message]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="card" aria-label="New campaign">
      <h2>New synthetic campaign</h2>
      <p className="note">All campaigns are synthetic planning data. Times are UTC.</p>
      <label>
        Name
        <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      </label>
      <label>
        Objective
        <input value={form.objective} onChange={(e) => setForm({ ...form, objective: e.target.value })} />
      </label>
      <label>
        Start (UTC)
        <input
          type="datetime-local"
          value={form.start_local}
          onChange={(e) => setForm({ ...form, start_local: e.target.value })}
        />
      </label>

      <h3>Vessels</h3>
      <table>
        <thead>
          <tr><th>Key</th><th>Name</th><th>Class</th><th>Home port</th><th>Turnaround h</th></tr>
        </thead>
        <tbody>
          {form.vessels.map((v, i) => (
            <tr key={i}>
              <td><input aria-label={`vessel ${i + 1} key`} value={v.key} onChange={(e) => setVessel(i, { key: e.target.value })} /></td>
              <td><input aria-label={`vessel ${i + 1} name`} value={v.name} onChange={(e) => setVessel(i, { name: e.target.value })} /></td>
              <td><input aria-label={`vessel ${i + 1} class`} value={v.vessel_class} onChange={(e) => setVessel(i, { vessel_class: e.target.value })} /></td>
              <td><input aria-label={`vessel ${i + 1} home port`} value={v.home_port} onChange={(e) => setVessel(i, { home_port: e.target.value })} /></td>
              <td><input aria-label={`vessel ${i + 1} turnaround`} type="number" min="0" step="0.5" value={v.turnaround_hours} onChange={(e) => setVessel(i, { turnaround_hours: e.target.value })} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <button type="button" onClick={() => setForm((f) => ({ ...f, vessels: [...f.vessels, emptyVessel(f.vessels.length + 1)] }))}>
        Add vessel
      </button>

      <h3>Tasks</h3>
      <table>
        <thead>
          <tr><th>Key</th><th>Name</th><th>Kind</th><th>Hours</th><th>Vessel key</th><th>Depends on (keys)</th></tr>
        </thead>
        <tbody>
          {form.tasks.map((t, i) => (
            <tr key={i}>
              <td><input aria-label={`task ${i + 1} key`} value={t.key} onChange={(e) => setTask(i, { key: e.target.value })} /></td>
              <td><input aria-label={`task ${i + 1} name`} value={t.name} onChange={(e) => setTask(i, { name: e.target.value })} /></td>
              <td><input aria-label={`task ${i + 1} kind`} value={t.kind} onChange={(e) => setTask(i, { kind: e.target.value })} /></td>
              <td><input aria-label={`task ${i + 1} hours`} type="number" min="0.25" step="0.25" value={t.duration_hours} onChange={(e) => setTask(i, { duration_hours: e.target.value })} /></td>
              <td><input aria-label={`task ${i + 1} vessel`} value={t.vessel} onChange={(e) => setTask(i, { vessel: e.target.value })} /></td>
              <td><input aria-label={`task ${i + 1} depends on`} value={t.depends_on} onChange={(e) => setTask(i, { depends_on: e.target.value })} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        type="button"
        onClick={() =>
          setForm((f) => ({ ...f, tasks: [...f.tasks, emptyTask(f.tasks.length + 1, f.vessels[0]?.key ?? "")] }))
        }
      >
        Add task
      </button>

      {errors.length > 0 && (
        <ul role="alert" className="errors">
          {errors.map((e) => <li key={e}>{e}</li>)}
        </ul>
      )}
      <div>
        <button type="submit" disabled={busy}>{busy ? "Planning..." : "Create and schedule"}</button>
      </div>
    </form>
  );
}
