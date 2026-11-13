import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Campaign, CampaignInput } from "./api";
import { CampaignFormView } from "./components/CampaignFormView";
import { Gantt } from "./components/CampaignView";
import { escapeExceptEm, SearchPanel } from "./components/SearchPanel";
import { SparqlConsole } from "./components/SparqlConsole";

describe("CampaignFormView", () => {
  it("submits vessels and tasks with dependencies", async () => {
    const user = userEvent.setup();
    const created = { id: 3 } as Campaign;
    const create = vi.fn(async (_: CampaignInput) => created);
    const onCreated = vi.fn();
    render(<CampaignFormView create={create} onCreated={onCreated} />);

    await user.type(screen.getByLabelText("Name"), "SYNTHETIC ui test");
    fireEvent.change(screen.getByLabelText("Start (UTC)"), { target: { value: "2026-03-02T06:00" } });
    await user.type(screen.getByLabelText("vessel 1 name"), "MV A");
    await user.type(screen.getByLabelText("vessel 1 class"), "tug");
    await user.type(screen.getByLabelText("task 1 name"), "Tow");
    await user.type(screen.getByLabelText("task 1 kind"), "tow");
    await user.click(screen.getByText("Add task"));
    await user.type(screen.getByLabelText("task 2 name"), "Return");
    await user.type(screen.getByLabelText("task 2 kind"), "transit");
    await user.type(screen.getByLabelText("task 2 depends on"), "t1");
    await user.click(screen.getByText("Create and schedule"));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created));
    const body = create.mock.calls[0][0];
    expect(body.start_time).toBe("2026-03-02T06:00:00+00:00");
    expect(body.vessels).toEqual([{ key: "v1", name: "MV A", vessel_class: "tug", home_port: "", turnaround_hours: 0 }]);
    expect(body.tasks.map((t) => [t.key, t.vessel, t.depends_on])).toEqual([
      ["t1", "v1", []],
      ["t2", "v1", ["t1"]],
    ]);
  });

  it("shows validation errors without calling the API", async () => {
    const user = userEvent.setup();
    const create = vi.fn();
    render(<CampaignFormView create={create} onCreated={() => {}} />);
    await user.click(screen.getByText("Create and schedule"));
    expect(screen.getByRole("alert")).toHaveTextContent("Campaign name is required.");
    expect(create).not.toHaveBeenCalled();
  });

  it("shows the server's error message", async () => {
    const user = userEvent.setup();
    const create = vi.fn(async () => {
      throw new Error("422: dependency cycle among tasks [1, 2]");
    });
    render(<CampaignFormView create={create} onCreated={() => {}} />);
    await user.type(screen.getByLabelText("Name"), "x");
    fireEvent.change(screen.getByLabelText("Start (UTC)"), { target: { value: "2026-03-02T06:00" } });
    await user.click(screen.getByText("Create and schedule"));
    expect(await screen.findByRole("alert")).toHaveTextContent("dependency cycle");
  });
});

describe("Gantt", () => {
  it("draws one lane per vessel with bars for its tasks", () => {
    const c = {
      start_time: "2026-03-02T06:00:00Z",
      makespan_hours: 4,
      vessels: [
        { id: 1, name: "MV A" },
        { id: 2, name: "MV B" },
      ],
      tasks: [
        { id: 7, name: "Survey" },
        { id: 8, name: "Tow" },
      ],
      schedule: [
        { task_id: 7, vessel_id: 1, start: "2026-03-02T06:00:00Z", end: "2026-03-02T08:00:00Z" },
        { task_id: 8, vessel_id: 2, start: "2026-03-02T08:00:00Z", end: "2026-03-02T10:00:00Z" },
      ],
    } as unknown as Campaign;
    render(<Gantt campaign={c} />);
    expect(screen.getByText("Tow")).toHaveStyle({ left: "50%", width: "50%" });
    expect(screen.getByText("Survey").closest(".lane")).toHaveTextContent("MV A");
  });
});

describe("SparqlConsole", () => {
  it("runs the query and renders the result table", async () => {
    const user = userEvent.setup();
    const run = vi.fn(async () => ({
      head: { vars: ["vessel", "task"] },
      results: { bindings: [{ vessel: { type: "literal", value: "MV A" }, task: { type: "literal", value: "Tow" } }] },
    }));
    render(<SparqlConsole run={run} />);
    await user.click(screen.getByText("Run query"));
    const table = await screen.findByRole("table", { name: "sparql results" });
    expect(table).toHaveTextContent("vesseltaskMV ATow");
    expect(run.mock.calls[0][0]).toContain("mcw:ScheduledActivity");
  });

  it("shows server-side SPARQL errors", async () => {
    const user = userEvent.setup();
    render(<SparqlConsole run={async () => { throw new Error("400: only SELECT and ASK queries are accepted"); }} />);
    await user.click(screen.getByText("Run query"));
    expect(await screen.findByRole("alert")).toHaveTextContent("only SELECT and ASK");
  });
});

describe("SearchPanel", () => {
  it("lists hits and keeps only <em> highlighting", async () => {
    const user = userEvent.setup();
    const search = vi.fn(async () => [
      {
        document_id: "d1",
        campaign_id: 1,
        campaign_name: "SYNTHETIC c",
        title: "Brief",
        filename: "b.md",
        tags: ["brief", "synthetic"],
        score: 1,
        highlight: "the <em>buoy</em> <script>x</script>",
      },
    ]);
    render(<SearchPanel search={search} />);
    await user.type(screen.getByLabelText("search query"), "buoy");
    await user.click(screen.getByText("Search"));
    const list = await screen.findByRole("list", { name: "search results" });
    expect(search).toHaveBeenCalledWith("buoy");
    expect(list).toHaveTextContent("Brief in SYNTHETIC c [brief, synthetic]");
    expect(list.querySelector("em")?.textContent).toBe("buoy");
    expect(list.querySelector("script")).toBeNull();
  });

  it("escapes markup except em", () => {
    expect(escapeExceptEm("<em>a</em> & <b>")).toBe("<em>a</em> &amp; &lt;b&gt;");
  });
});
