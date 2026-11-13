import type { Campaign, CampaignInput, SparqlResult } from "./api";

export interface VesselRow {
  key: string;
  name: string;
  vessel_class: string;
  home_port: string;
  turnaround_hours: string;
}

export interface TaskRow {
  key: string;
  name: string;
  kind: string;
  duration_hours: string;
  vessel: string;
  depends_on: string;
}

export interface CampaignForm {
  name: string;
  objective: string;
  start_local: string; // value of <input type="datetime-local">, interpreted as UTC
  vessels: VesselRow[];
  tasks: TaskRow[];
}

/** Turn form rows into the API payload; returns a list of problems instead when invalid. */
export function toPayload(form: CampaignForm): { payload?: CampaignInput; errors: string[] } {
  const errors: string[] = [];
  if (!form.name.trim()) errors.push("Campaign name is required.");
  if (!form.start_local) errors.push("Start time is required.");
  const vesselKeys = form.vessels.map((v) => v.key.trim());
  const taskKeys = form.tasks.map((t) => t.key.trim());
  if (form.vessels.length === 0) errors.push("Add at least one vessel.");
  if (form.tasks.length === 0) errors.push("Add at least one task.");
  if (new Set(vesselKeys).size !== vesselKeys.length) errors.push("Vessel keys must be unique.");
  if (new Set(taskKeys).size !== taskKeys.length) errors.push("Task keys must be unique.");

  const tasks = form.tasks.map((t) => {
    const deps = t.depends_on.split(",").map((d) => d.trim()).filter(Boolean);
    const hours = Number(t.duration_hours);
    if (!(hours > 0)) errors.push(`Task "${t.key}" needs a positive duration.`);
    if (!vesselKeys.includes(t.vessel.trim())) errors.push(`Task "${t.key}" uses unknown vessel "${t.vessel}".`);
    for (const d of deps) if (!taskKeys.includes(d)) errors.push(`Task "${t.key}" depends on unknown task "${d}".`);
    return {
      key: t.key.trim(),
      name: t.name.trim(),
      kind: t.kind.trim(),
      duration_hours: hours,
      vessel: t.vessel.trim(),
      depends_on: deps,
    };
  });
  if (errors.length) return { errors };
  return {
    errors,
    payload: {
      name: form.name.trim(),
      objective: form.objective.trim(),
      start_time: `${form.start_local.length === 16 ? `${form.start_local}:00` : form.start_local}+00:00`,
      vessels: form.vessels.map((v) => ({
        key: v.key.trim(),
        name: v.name.trim(),
        vessel_class: v.vessel_class.trim(),
        home_port: v.home_port.trim(),
        turnaround_hours: Number(v.turnaround_hours) || 0,
      })),
      tasks,
    },
  };
}

export interface Bar {
  taskId: number;
  label: string;
  vessel: string;
  offsetPct: number;
  widthPct: number;
  startHour: number;
  endHour: number;
}

/** Gantt layout: one bar per scheduled task, positioned relative to the campaign start. */
export function ganttBars(c: Campaign): Bar[] {
  const t0 = Date.parse(c.start_time);
  const span = Math.max(c.makespan_hours, 1e-9);
  const taskName = new Map(c.tasks.map((t) => [t.id, t.name]));
  const vesselName = new Map(c.vessels.map((v) => [v.id, v.name]));
  return c.schedule.map((s) => {
    const startHour = (Date.parse(s.start) - t0) / 3_600_000;
    const endHour = (Date.parse(s.end) - t0) / 3_600_000;
    return {
      taskId: s.task_id,
      label: taskName.get(s.task_id) ?? `task ${s.task_id}`,
      vessel: vesselName.get(s.vessel_id) ?? `vessel ${s.vessel_id}`,
      offsetPct: (startHour / span) * 100,
      widthPct: ((endHour - startHour) / span) * 100,
      startHour,
      endHour,
    };
  });
}

/** Flatten SPARQL JSON results into a header row and string cells. */
export function sparqlTable(r: SparqlResult): { columns: string[]; rows: string[][] } {
  if (typeof r.boolean === "boolean") return { columns: ["ASK"], rows: [[String(r.boolean)]] };
  const columns = r.head.vars ?? [];
  const rows = (r.results?.bindings ?? []).map((b) => columns.map((c) => b[c]?.value ?? ""));
  return { columns, rows };
}

export const SAMPLE_QUERIES: Record<string, string> = {
  "Schedule by vessel": `PREFIX mcw: <https://github.com/MaheshBhushan/maritime-campaign-workbench/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?campaign ?vessel ?task ?start ?end WHERE {
  ?a a mcw:ScheduledActivity ; mcw:inCampaign ?c ; mcw:onVessel ?v ; mcw:schedulesTask ?t ;
     mcw:startTime ?start ; mcw:endTime ?end .
  ?c rdfs:label ?campaign . ?v rdfs:label ?vessel . ?t rdfs:label ?task .
} ORDER BY ?campaign ?vessel ?start`,
  "Task dependency chains": `PREFIX mcw: <https://github.com/MaheshBhushan/maritime-campaign-workbench/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?task ?prerequisite WHERE {
  ?t mcw:dependsOn+ ?p . ?t rdfs:label ?task . ?p rdfs:label ?prerequisite .
} ORDER BY ?task ?prerequisite`,
  "Entities per class (uses ontology)": `PREFIX mcw: <https://github.com/MaheshBhushan/maritime-campaign-workbench/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?class (COUNT(?e) AS ?n) WHERE {
  ?e a ?cls . ?cls rdfs:subClassOf mcw:CampaignEntity ; rdfs:label ?class .
} GROUP BY ?class ORDER BY ?class`,
  "Documents and checksums": `PREFIX mcw: <https://github.com/MaheshBhushan/maritime-campaign-workbench/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?title ?key ?sha256 WHERE {
  ?d a mcw:Document ; rdfs:label ?title ; mcw:objectKey ?key ; mcw:sha256 ?sha256 .
}`,
};
