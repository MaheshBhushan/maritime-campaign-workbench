# Maritime Campaign Workbench

A planner for **synthetic** maritime campaigns. You describe a campaign as vessels and tasks
(with durations and dependencies), the API schedules it, stores the entities in Postgres,
keeps attached documents in MinIO with their metadata indexed in OpenSearch, and mirrors
everything as RDF in Apache Jena Fuseki under a small checked-in ontology so it can be
queried with SPARQL. A cross-service fixture check proves that the four stores agree.

All campaign data in this repository and produced by the tool is synthetic. Vessel names,
ports, positions and documents are invented; the tool describes no real programme,
operation or organisation, and it has not been deployed anywhere.

## Where it comes from

It extends the planning idea of my earlier project
[NeuroPlan](https://github.com/MaheshBhushan/NeuroPlan): tasks go in, a timeline of time
blocks comes out. NeuroPlan asked an LLM (Gemini) to produce a daily plan for one person.
Here the planner is deterministic and constraint-aware for several resources:

- a task starts no earlier than the campaign start and only after all its dependencies end;
- a vessel performs one task at a time;
- a vessel idles for its turnaround time between consecutive tasks.

The scheduler (`backend/mcw/scheduler.py`) is greedy list scheduling: among tasks whose
dependencies are placed, schedule the one that can start earliest (ties by id), repeat.
Unknown vessels, non-positive durations and dependency cycles are rejected with HTTP 422.
It is not an optimiser; it produces a feasible plan, not a provably shortest one.

## Architecture

```
React/TS UI (nginx :18480) --/api--> FastAPI (:18481)
                                       |-- Postgres   system of record: campaigns, vessels, tasks,
                                       |               task dependencies, schedule, document rows
                                       |-- MinIO      document bytes, key campaigns/<id>/documents/<uuid>/<file>,
                                       |               sha256 stored as object metadata
                                       |-- OpenSearch index mcw-documents: metadata + extracted text
                                       |               of text documents, full-text search
                                       '-- Fuseki     dataset mcw (TDB2, union default graph):
                                                       ontology graph + one named graph per campaign
```

Write path: Postgres commits first; then the MinIO object (for uploads), the OpenSearch
record and the campaign's named graph in Fuseki are written. The RDF graph for a campaign is
regenerated from Postgres and replaced as a whole (Graph Store Protocol `PUT`), so it never
accumulates stale triples. Deleting a campaign removes it from all four stores.

Ontology: [`ontology/mcw.ttl`](ontology/mcw.ttl) defines `mcw:Campaign`, and the
`mcw:CampaignEntity` subclasses `Vessel`, `Task`, `ScheduledActivity` and `Document`, with
properties such as `mcw:assignedVessel`, `mcw:dependsOn` (transitive), `mcw:schedulesTask`,
`mcw:onVessel`, `mcw:startTime`, `mcw:sha256`, `mcw:objectKey` and `mcw:isSynthetic`. A unit
test asserts that the RDF mirror uses only terms declared in the ontology.

The API exposes SPARQL at `POST /api/sparql`; only `SELECT` and `ASK` are accepted (parsed
with rdflib before forwarding), updates go nowhere near the public endpoint.

Main endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/campaigns` | create a campaign with vessels and tasks; returns the schedule |
| `GET` | `/api/campaigns`, `/api/campaigns/{id}` | list, detail |
| `DELETE` | `/api/campaigns/{id}` | delete from Postgres, MinIO, OpenSearch and Fuseki |
| `POST` | `/api/campaigns/{id}/documents` | multipart upload: `file`, `title`, `tags` |
| `GET` | `/api/documents/{id}/content` | download from MinIO |
| `GET` | `/api/search?q=&campaign_id=&tag=` | OpenSearch query |
| `POST` | `/api/sparql` | SPARQL SELECT/ASK against Fuseki |
| `GET` | `/api/campaigns/{id}/rdf`, `/api/ontology` | Turtle of a campaign / the ontology |
| `POST` | `/api/fixture` | load the fixture campaign if absent |
| `GET` | `/api/campaigns/{id}/consistency` | cross-service check report |
| `GET` | `/api/health` | reachability of all four services |

## Cross-service fixture check

[`fixtures/campaign.json`](fixtures/campaign.json) is a synthetic campaign (3 vessels,
6 tasks, 4 dependency edges, 2 documents in `fixtures/documents/`). `mcw-fixture-check`
creates it if missing, then verifies:

- Postgres: names, dependency edges and document titles equal the fixture; every task is
  scheduled once and the schedule satisfies dependency, vessel-exclusivity and turnaround
  constraints;
- MinIO: object keys equal the Postgres keys; size and SHA-256 recomputed from the stored
  bytes equal the Postgres values and the object metadata;
- OpenSearch: one record per document with matching title, filename, size, hash, key, tags
  and campaign name; each text document is found by a title search;
- Fuseki (via SPARQL): the campaign node and its synthetic flag, entity counts per class,
  `dependsOn` edges, every schedule slot (task, vessel, start, end) and document
  key/hash/size equal Postgres; the ontology graph is loaded.

An integration test removes one MinIO object and asserts that only the MinIO checks fail,
then restores it. The same check runs for any campaign from the UI ("Check Postgres /
MinIO / OpenSearch / Fuseki").

## Quickstart

Requires Docker with Compose v2. The stack is memory-capped (about 2.6 GB in total, with
OpenSearch at a 512 MB heap). Host ports bind to 127.0.0.1.

```bash
docker compose up -d --build --wait
./scripts/smoke.sh                 # end-to-end flow through the UI proxy
open http://localhost:18480        # UI
docker compose down -v             # stop and delete volumes
```

| Service | Host port |
| --- | --- |
| UI (nginx, proxies `/api`) | 18480 |
| API | 18481 |
| Postgres | 18482 |
| MinIO API / console | 18483 / 18484 |
| OpenSearch | 18485 |
| Fuseki | 18486 |

In the UI: "Load fixture campaign" or fill in the form (vessels, tasks with `depends on`
keys), then view the Gantt chart and schedule table, attach a document, search documents,
run SPARQL queries from the examples, and run the consistency check.

## Tests

```bash
# backend unit tests (no services needed)
cd backend && uv sync && uv run pytest

# backend integration tests and the fixture check against running services
docker compose up -d postgres minio opensearch fuseki --wait
MCW_INTEGRATION=1 uv run pytest
uv run mcw-fixture-check

# frontend
cd frontend && npm ci && npm test && npm run build
```

CI (`.github/workflows/ci.yml`) runs three jobs: backend pytest with Postgres, MinIO,
OpenSearch and Fuseki as GitHub Actions service containers (integration tests enabled)
followed by `mcw-fixture-check`; frontend Vitest, type check and build; and a job that runs
`docker compose up --build --wait` and `scripts/smoke.sh` against the full stack.

## Measured results

All figures below come from runs of the commands in this repository on 2026-11-13; they are
correctness results, not performance benchmarks.

- Backend pytest: 23 unit tests pass without services (4 integration tests skipped); with
  `MCW_INTEGRATION=1` against the compose services all 27 pass, locally and in CI.
- Frontend Vitest: 14 tests in 2 files pass in CI; `tsc --noEmit` reports no errors.
- `mcw-fixture-check` on the fixture campaign: 21/21 checks pass (Postgres 7, MinIO 3,
  OpenSearch 5, Fuseki 6), locally and in CI. Fuseki reports 3 vessels, 6 tasks,
  6 scheduled activities and 2 documents for it.
- The fixture campaign's schedule has a makespan of 25 h (start 2026-03-02T06:00Z, last
  task ends 2026-03-03T07:00Z), which matches the hand-computed value asserted in
  `tests/test_scheduler.py`.
- `scripts/smoke.sh` against `docker compose up` (locally and in CI): UI served, all four
  services healthy, a 3-task campaign scheduled with a 6 h makespan, an uploaded document
  downloaded byte-identical from MinIO, found by full-text search in OpenSearch, its tasks
  returned by SPARQL from Fuseki, 14/14 consistency checks passing for it and 21/21 for the
  fixture, and the campaign removed from all stores on delete.
- The same flow was exercised by hand in a headless Chromium against the UI: create a
  2-vessel, 2-task campaign through the form (makespan 5 h), attach a text file, run the
  consistency check (14 passed, 0 failed), find the file by a word in its body, and run the
  "Schedule by vessel" SPARQL example.

## Limitations

- Synthetic data only; there is no import of real AIS, port or vessel data.
- The scheduler is greedy and does not minimise makespan; it has no transit-distance,
  weather or port-capacity model. Campaigns are created in one request and are not
  editable afterwards (delete and recreate).
- Writes to MinIO, OpenSearch and Fuseki happen after the Postgres commit without a
  distributed transaction or outbox; if a secondary store is down mid-request the stores can
  drift. The consistency check detects that drift; it does not repair it.
- Only text-like uploads (`text/*`, JSON, XML, YAML) have their contents indexed; other
  files are searchable by metadata only.
- No authentication on the API or UI; credentials in `docker-compose.yml` are local
  development defaults. OpenSearch runs with its security plugin disabled and with the
  disk-watermark allocation threshold turned off so it works on nearly full developer
  disks. None of this is production configuration.
- It has not been deployed to any cloud or programme environment.

## License

MIT
