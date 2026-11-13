"""End-to-end tests against real Postgres, MinIO, OpenSearch and Fuseki.

Run with MCW_INTEGRATION=1 and the MCW_* service URLs pointing at running
services (docker compose locally, service containers in CI).
"""

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from mcw.config import Settings
from mcw.fixture_check import check_campaign, ensure_fixture, fixture_spec
from mcw.main import create_app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("MCW_INTEGRATION") != "1", reason="set MCW_INTEGRATION=1 to run"),
]

PREFIX = (
    "PREFIX mcw: <https://github.com/MaheshBhushan/maritime-campaign-workbench/ontology#>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
)


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as c:
        yield c


def test_health(client):
    body = client.get("/api/health").json()
    assert body == {"ok": True, "services": {"postgres": True, "minio": True, "opensearch": True, "fuseki": True}}


def test_main_flow_create_attach_search_sparql_delete(client):
    marker = uuid.uuid4().hex[:8]
    r = client.post("/api/campaigns", json={
        "name": f"SYNTHETIC integration {marker}",
        "objective": "synthetic",
        "start_time": "2026-05-01T08:00:00+02:00",
        "vessels": [
            {"key": "a", "name": f"MV Alpha {marker}", "vessel_class": "survey", "turnaround_hours": 1},
            {"key": "b", "name": f"MV Bravo {marker}", "vessel_class": "tug"},
        ],
        "tasks": [
            {"key": "s", "name": "Survey", "kind": "survey", "duration_hours": 5, "vessel": "a"},
            {"key": "t", "name": "Tow", "kind": "tow", "duration_hours": 2, "vessel": "b", "depends_on": ["s"]},
            {"key": "u", "name": "Resurvey", "kind": "survey", "duration_hours": 1, "vessel": "a"},
        ],
    })
    assert r.status_code == 201, r.text
    c = r.json()
    cid = c["id"]
    assert c["synthetic"] is True
    assert c["makespan_hours"] == 7
    slots = {s["task_id"]: s for s in c["schedule"]}
    names = {t["name"]: t["id"] for t in c["tasks"]}
    assert slots[names["Tow"]]["start"] == slots[names["Survey"]]["end"]

    content = f"Synthetic notice {marker}: anchorage closed for fictional trials.".encode()
    r = client.post(
        f"/api/campaigns/{cid}/documents",
        files={"file": ("notice.txt", content, "text/plain")},
        data={"title": "Synthetic notice", "tags": "notice, ops"},
    )
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["tags"] == ["notice", "ops", "synthetic"]
    assert doc["object_key"].startswith(f"campaigns/{cid}/documents/")

    assert client.get(f"/api/documents/{doc['id']}/content").content == content

    hits = client.get("/api/search", params={"q": marker}).json()
    assert [h["document_id"] for h in hits] == [doc["id"]]
    assert hits[0]["campaign_id"] == cid and marker in hits[0]["highlight"]
    assert [h["document_id"] for h in client.get("/api/search", params={"campaign_id": cid, "tag": "ops"}).json()] == [doc["id"]]

    q = PREFIX + f"""SELECT ?task ?vessel WHERE {{
        ?a a mcw:ScheduledActivity ; mcw:schedulesTask ?t ; mcw:onVessel ?v .
        ?t rdfs:label ?task . ?v rdfs:label ?vessel . FILTER(CONTAINS(?vessel, "{marker}")) }} ORDER BY ?task"""
    rows = client.post("/api/sparql", json={"query": q}).json()["results"]["bindings"]
    assert [(b["task"]["value"], b["vessel"]["value"].split()[1]) for b in rows] == [
        ("Resurvey", "Alpha"), ("Survey", "Alpha"), ("Tow", "Bravo")]
    ask = PREFIX + f'ASK {{ ?d a mcw:Document ; mcw:sha256 "{doc["sha256"]}" }}'
    assert client.post("/api/sparql", json={"query": ask}).json()["boolean"] is True

    report = client.get(f"/api/campaigns/{cid}/consistency").json()
    assert report["failed"] == 0, [x for x in report["checks"] if not x["ok"]]

    assert client.delete(f"/api/campaigns/{cid}").status_code == 204
    assert client.get(f"/api/campaigns/{cid}").status_code == 404
    assert client.get("/api/search", params={"q": marker}).json() == []
    assert client.post("/api/sparql", json={"query": ask}).json()["boolean"] is False


def test_fixture_campaign_consistent_across_services(client):
    wb = client.app.state.wb
    with wb.db.sessions() as s:
        c = ensure_fixture(wb, s)
        checks = check_campaign(wb, c, fixture_spec(Settings().fixtures_dir))
    failed = [x for x in checks if not x.ok]
    assert not failed, failed
    assert {x.service for x in checks} == {"postgres", "minio", "opensearch", "fuseki"}
    assert len(c.documents) == 2 and len(c.tasks) == 6


def test_fixture_check_detects_drift(client):
    """Deleting the fixture's MinIO object must make the check fail, then restoring it fixes it."""
    wb = client.app.state.wb
    with wb.db.sessions() as s:
        c = ensure_fixture(wb, s)
        d = c.documents[0]
        data = wb.store.get(d.object_key)
        wb.store.client.remove_object(wb.store.bucket, d.object_key)
        try:
            failed = [x for x in check_campaign(wb, c) if not x.ok]
            assert {x.service for x in failed} == {"minio"}
        finally:
            wb.store.put(d.object_key, data, d.content_type, {"sha256": d.sha256})
        assert all(x.ok for x in check_campaign(wb, c))
