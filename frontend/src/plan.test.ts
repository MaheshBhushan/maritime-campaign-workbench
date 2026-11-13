import { describe, expect, it } from "vitest";
import type { Campaign } from "./api";
import { ganttBars, sparqlTable, toPayload, type CampaignForm } from "./plan";

const form = (over: Partial<CampaignForm> = {}): CampaignForm => ({
  name: "SYNTHETIC test",
  objective: "",
  start_local: "2026-03-02T06:00",
  vessels: [{ key: "a", name: "MV A", vessel_class: "tug", home_port: "", turnaround_hours: "1.5" }],
  tasks: [
    { key: "t1", name: "Tow", kind: "tow", duration_hours: "2", vessel: "a", depends_on: "" },
    { key: "t2", name: "Return", kind: "transit", duration_hours: "1", vessel: "a", depends_on: " t1 " },
  ],
  ...over,
});

describe("toPayload", () => {
  it("builds the API payload with UTC start, numbers and dependency lists", () => {
    const { payload, errors } = toPayload(form());
    expect(errors).toEqual([]);
    expect(payload).toMatchObject({
      start_time: "2026-03-02T06:00:00+00:00",
      vessels: [{ key: "a", turnaround_hours: 1.5 }],
      tasks: [
        { key: "t1", duration_hours: 2, depends_on: [] },
        { key: "t2", depends_on: ["t1"] },
      ],
    });
  });

  it("reports unknown vessels, unknown dependencies and bad durations", () => {
    const { payload, errors } = toPayload(
      form({ tasks: [{ key: "t1", name: "x", kind: "k", duration_hours: "0", vessel: "zz", depends_on: "nope" }] }),
    );
    expect(payload).toBeUndefined();
    expect(errors).toEqual([
      'Task "t1" needs a positive duration.',
      'Task "t1" uses unknown vessel "zz".',
      'Task "t1" depends on unknown task "nope".',
    ]);
  });

  it("rejects duplicate keys and missing name", () => {
    const f = form({ name: " " });
    f.vessels.push({ ...f.vessels[0] });
    expect(toPayload(f).errors).toEqual(["Campaign name is required.", "Vessel keys must be unique."]);
  });
});

describe("ganttBars", () => {
  it("positions bars relative to the campaign start and makespan", () => {
    const c: Campaign = {
      id: 1,
      name: "c",
      objective: "",
      start_time: "2026-03-02T06:00:00Z",
      synthetic: true,
      makespan_hours: 10,
      vessels: [{ id: 1, name: "MV A", vessel_class: "", home_port: "", turnaround_hours: 0 }],
      tasks: [{ id: 5, name: "Survey", kind: "survey", duration_hours: 4, vessel_id: 1, depends_on: [] }],
      schedule: [{ task_id: 5, vessel_id: 1, start: "2026-03-02T08:00:00Z", end: "2026-03-02T12:00:00Z" }],
      documents: [],
    };
    expect(ganttBars(c)).toEqual([
      { taskId: 5, label: "Survey", vessel: "MV A", offsetPct: 20, widthPct: 40, startHour: 2, endHour: 6 },
    ]);
  });
});

describe("sparqlTable", () => {
  it("flattens SELECT bindings in variable order, blank for unbound", () => {
    expect(
      sparqlTable({
        head: { vars: ["a", "b"] },
        results: { bindings: [{ b: { type: "literal", value: "2" }, a: { type: "uri", value: "x" } }, { a: { type: "literal", value: "y" } }] },
      }),
    ).toEqual({ columns: ["a", "b"], rows: [["x", "2"], ["y", ""]] });
  });

  it("renders ASK results", () => {
    expect(sparqlTable({ head: {}, boolean: false })).toEqual({ columns: ["ASK"], rows: [["false"]] });
  });
});
