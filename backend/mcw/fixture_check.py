"""Cross-service consistency check.

Loads (or finds) the checked-in fixture campaign and verifies that Postgres,
MinIO, OpenSearch and Fuseki all describe the same campaign:

* Postgres matches the fixture file (vessels, tasks, dependencies, documents)
  and the stored schedule satisfies every planning constraint;
* every document object exists in MinIO with the size and SHA-256 recorded in
  Postgres, recomputed from the stored bytes;
* OpenSearch holds exactly one metadata record per document with matching
  fields, and a full-text query finds each text document;
* the Fuseki named graph mirrors every entity, dependency edge, schedule slot
  and document checksum, queried through SPARQL.

``check_campaign`` works for any campaign, not only the fixture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import Campaign
from .rdf import DATA, MCW
from .schemas import CampaignIn
from .service import Workbench, object_prefix


@dataclass
class Check:
    service: str
    name: str
    ok: bool
    detail: str = ""


def fixture_spec(fixtures_dir: Path) -> dict:
    return json.loads((fixtures_dir / "campaign.json").read_text())


def ensure_fixture(wb: Workbench, s: Session) -> Campaign:
    """Return the fixture campaign, creating it and attaching its documents if absent."""
    spec = fixture_spec(wb.settings.fixtures_dir)
    existing = s.scalars(select(Campaign).where(Campaign.name == spec["name"]).order_by(Campaign.id)).first()
    if existing is not None:
        return wb.load(s, existing.id)
    c = wb.create_campaign(s, CampaignIn.model_validate({k: v for k, v in spec.items() if k != "documents"}))
    for d in spec["documents"]:
        path = wb.settings.fixtures_dir / "documents" / d["file"]
        wb.attach_document(
            s,
            c.id,
            title=d["title"],
            filename=path.name,
            content_type=d["content_type"],
            data=path.read_bytes(),
            tags=d.get("tags", []),
        )
    s.expire_all()
    return wb.load(s, c.id)


def _sparql_rows(wb: Workbench, query: str) -> list[dict[str, str]]:
    res = wb.fuseki.query(query)
    return [{k: v["value"] for k, v in b.items()} for b in res["results"]["bindings"]]


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def check_campaign(wb: Workbench, c: Campaign, spec: dict | None = None) -> list[Check]:
    checks: list[Check] = []

    def add(service: str, name: str, ok: bool, detail: str = "") -> None:
        checks.append(Check(service, name, bool(ok), detail))

    vessels = {v.id: v for v in c.vessels}
    tasks = {t.id: t for t in c.tasks}
    sched = {e.task_id: e for e in c.schedule}

    # ---- Postgres ----------------------------------------------------------
    add("postgres", "campaign is labelled synthetic", c.synthetic)
    if spec is not None:
        add("postgres", "vessel names match fixture",
            sorted(v.name for v in c.vessels) == sorted(v["name"] for v in spec["vessels"]))
        add("postgres", "task names match fixture",
            sorted(t.name for t in c.tasks) == sorted(t["name"] for t in spec["tasks"]))
        by_key = {t["key"]: t["name"] for t in spec["tasks"]}
        want_edges = sorted((t["name"], by_key[d]) for t in spec["tasks"] for d in t.get("depends_on", []))
        got_edges = sorted((t.name, d.name) for t in c.tasks for d in t.depends_on)
        add("postgres", "dependencies match fixture", want_edges == got_edges, f"{len(got_edges)} edges")
        add("postgres", "document titles match fixture",
            sorted(d.title for d in c.documents) == sorted(d["title"] for d in spec["documents"]))
    add("postgres", "every task scheduled exactly once",
        sorted(sched) == sorted(tasks) and len(c.schedule) == len(tasks), f"{len(c.schedule)} slots")
    violations = []
    for t in c.tasks:
        e = sched.get(t.id)
        if e is None:
            continue
        if e.start < c.start_time:
            violations.append(f"{t.name} starts before campaign")
        if abs((e.end - e.start) - timedelta(hours=t.duration_hours)) > timedelta(seconds=1):
            violations.append(f"{t.name} has wrong duration")
        if e.vessel_id != t.vessel_id:
            violations.append(f"{t.name} on wrong vessel")
        for d in t.depends_on:
            if d.id in sched and e.start < sched[d.id].end:
                violations.append(f"{t.name} starts before {d.name} ends")
    for vid, v in vessels.items():
        slots = sorted((e for e in c.schedule if e.vessel_id == vid), key=lambda e: e.start)
        for a, b in zip(slots, slots[1:]):
            if b.start < a.end + timedelta(hours=v.turnaround_hours):
                violations.append(f"{v.name} overlap/turnaround breach")
    add("postgres", "schedule satisfies dependency, vessel and turnaround constraints",
        not violations, "; ".join(violations))

    # ---- MinIO -------------------------------------------------------------
    keys = wb.store.list_keys(object_prefix(c.id))
    add("minio", "object keys equal Postgres document keys",
        keys == sorted(d.object_key for d in c.documents), f"{len(keys)} objects")
    for d in c.documents:
        st = wb.store.stat(d.object_key)
        if st is None:
            add("minio", f"{d.filename}: object exists", False)
            continue
        data = wb.store.get(d.object_key)
        add("minio", f"{d.filename}: size and sha256 match",
            st["size"] == d.size_bytes and hashlib.sha256(data).hexdigest() == d.sha256
            and st["metadata"].get("sha256") == d.sha256)

    # ---- OpenSearch --------------------------------------------------------
    indexed = {h["document_id"]: h for h in wb.index.docs_for_campaign(c.id)}
    add("opensearch", "indexed document ids equal Postgres ids",
        sorted(indexed) == sorted(d.id for d in c.documents), f"{len(indexed)} records")
    for d in c.documents:
        h = indexed.get(d.id)
        ok = h is not None and all(
            h.get(f) == getattr(d, f) for f in ("title", "filename", "sha256", "object_key", "size_bytes")
        ) and h.get("campaign_name") == c.name and h.get("synthetic") is True and sorted(h.get("tags", [])) == sorted(d.tags)
        add("opensearch", f"{d.filename}: metadata matches", ok)
        if d.content_type.startswith("text/"):
            hits = wb.index.search(d.title, campaign_id=c.id)
            add("opensearch", f"{d.filename}: findable by title search", any(x["document_id"] == d.id for x in hits))

    # ---- Fuseki ------------------------------------------------------------
    ci = f"<{DATA}campaign/{c.id}>"
    prefix = f"PREFIX mcw: <{MCW}>\nPREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    rows = _sparql_rows(wb, prefix + f"SELECT ?label ?syn WHERE {{ {ci} a mcw:Campaign ; rdfs:label ?label ; mcw:isSynthetic ?syn }}")
    add("fuseki", "campaign node with label and synthetic flag",
        len(rows) == 1 and rows[0]["label"] == c.name and rows[0]["syn"] == "true")
    rows = _sparql_rows(wb, prefix + f"""
        SELECT ?cls (COUNT(?e) AS ?n) WHERE {{ ?e mcw:inCampaign {ci} ; a ?cls }} GROUP BY ?cls""")
    counts = {r["cls"].rsplit("#", 1)[-1]: int(r["n"]) for r in rows}
    want = {"Vessel": len(c.vessels), "Task": len(c.tasks), "ScheduledActivity": len(c.schedule), "Document": len(c.documents)}
    add("fuseki", "entity counts per class match Postgres",
        all(counts.get(k, 0) == v for k, v in want.items()), json.dumps(counts, sort_keys=True))
    rows = _sparql_rows(wb, prefix + f"""
        SELECT ?a ?b WHERE {{ ?t mcw:inCampaign {ci} ; rdfs:label ?a ; mcw:dependsOn ?d . ?d rdfs:label ?b }}""")
    add("fuseki", "dependsOn edges match Postgres",
        sorted((r["a"], r["b"]) for r in rows) == sorted((t.name, d.name) for t in c.tasks for d in t.depends_on))
    rows = _sparql_rows(wb, prefix + f"""
        SELECT ?task ?vessel ?start ?end WHERE {{
          ?s a mcw:ScheduledActivity ; mcw:inCampaign {ci} ; mcw:schedulesTask ?t ; mcw:onVessel ?v ;
             mcw:startTime ?start ; mcw:endTime ?end .
          ?t rdfs:label ?task . ?v rdfs:label ?vessel }}""")
    got = sorted((r["task"], r["vessel"], _parse_dt(r["start"]), _parse_dt(r["end"])) for r in rows)
    want_slots = sorted((tasks[e.task_id].name, vessels[e.vessel_id].name, e.start, e.end) for e in c.schedule)
    add("fuseki", "schedule slots match Postgres", got == want_slots, f"{len(rows)} slots")
    rows = _sparql_rows(wb, prefix + f"""
        SELECT ?key ?sha ?size WHERE {{ ?d a mcw:Document ; mcw:inCampaign {ci} ; mcw:objectKey ?key ;
          mcw:sha256 ?sha ; mcw:sizeBytes ?size }}""")
    add("fuseki", "document keys, checksums and sizes match Postgres",
        sorted((r["key"], r["sha"], int(r["size"])) for r in rows)
        == sorted((d.object_key, d.sha256, d.size_bytes) for d in c.documents))
    rows = _sparql_rows(wb, prefix + "SELECT (COUNT(*) AS ?n) WHERE { mcw:Vessel rdfs:subClassOf mcw:CampaignEntity }")
    add("fuseki", "ontology graph loaded", rows and rows[0]["n"] == "1")
    return checks


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Load the fixture campaign and verify it across all four services.")
    p.add_argument("--campaign-id", type=int, help="check this campaign instead of the fixture")
    p.add_argument("--json", action="store_true", help="print machine-readable results")
    args = p.parse_args(argv)

    wb = Workbench.from_settings(Settings())
    wb.initialise()
    with wb.db.sessions() as s:
        if args.campaign_id is None:
            c = ensure_fixture(wb, s)
            spec = fixture_spec(wb.settings.fixtures_dir)
        else:
            c = wb.load(s, args.campaign_id)
            spec = None
        checks = check_campaign(wb, c, spec)
    failed = [x for x in checks if not x.ok]
    if args.json:
        print(json.dumps({"campaign_id": c.id, "passed": len(checks) - len(failed), "failed": len(failed),
                          "checks": [asdict(x) for x in checks]}, indent=2))
    else:
        for x in checks:
            print(f"[{'PASS' if x.ok else 'FAIL'}] {x.service:<10} {x.name}" + (f" ({x.detail})" if x.detail else ""))
        print(f"campaign {c.id}: {len(checks) - len(failed)}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
