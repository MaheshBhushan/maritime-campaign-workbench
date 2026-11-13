import { useCallback, useEffect, useState } from "react";
import type { Campaign, CampaignSummary } from "./api";
import { api } from "./api";
import { CampaignFormView } from "./components/CampaignFormView";
import { CampaignView } from "./components/CampaignView";
import { SearchPanel } from "./components/SearchPanel";
import { SparqlConsole } from "./components/SparqlConsole";

export function App() {
  const [campaigns, setCampaigns] = useState<CampaignSummary[]>([]);
  const [selected, setSelected] = useState<Campaign | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setCampaigns(await api.listCampaigns());
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function open(id: number) {
    setSelected(await api.getCampaign(id));
  }

  async function loadFixture() {
    setSelected(await api.loadFixture());
    await refresh();
  }

  return (
    <main>
      <header>
        <h1>Maritime Campaign Workbench</h1>
        <p className="banner">
          Synthetic data only. Every campaign, vessel, port and document in this tool is invented for planning
          experiments and describes no real programme or operation.
        </p>
      </header>
      {error && <p role="alert" className="errors">{error}</p>}
      <div className="layout">
        <aside className="card">
          <h2>Campaigns</h2>
          <button onClick={loadFixture}>Load fixture campaign</button>
          <button onClick={() => setSelected(null)}>New campaign</button>
          <ul aria-label="campaigns">
            {campaigns.map((c) => (
              <li key={c.id}>
                <button className="link" onClick={() => open(c.id)}>
                  {c.name}
                </button>{" "}
                ({c.vessel_count} vessels, {c.task_count} tasks, {c.document_count} docs)
              </li>
            ))}
          </ul>
        </aside>
        <div>
          {selected ? (
            <CampaignView
              key={selected.id}
              campaign={selected}
              onChanged={(c) => {
                setSelected(c);
                void refresh();
              }}
              onDeleted={() => {
                setSelected(null);
                void refresh();
              }}
            />
          ) : (
            <CampaignFormView
              onCreated={(c) => {
                setSelected(c);
                void refresh();
              }}
            />
          )}
          <SearchPanel />
          <SparqlConsole />
        </div>
      </div>
    </main>
  );
}
