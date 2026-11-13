"""API behaviour that is decided before any backing service is contacted."""

import pytest
from fastapi.testclient import TestClient

from mcw.main import create_app
from mcw.service import extract_text


@pytest.fixture
def client():
    # initialise=False: no service is contacted at startup; the requests below are
    # rejected during validation, so they never reach Postgres/MinIO/OpenSearch/Fuseki.
    with TestClient(create_app(initialise=False)) as c:
        yield c


def campaign(**over):
    body = {
        "name": "SYNTHETIC unit",
        "start_time": "2026-03-02T06:00:00+00:00",
        "vessels": [{"key": "a", "name": "MV A", "vessel_class": "tug"}],
        "tasks": [{"key": "t1", "name": "T1", "kind": "tow", "duration_hours": 1, "vessel": "a"}],
    }
    body.update(over)
    return body


@pytest.mark.parametrize(
    "body,fragment",
    [
        (campaign(tasks=[{"key": "t1", "name": "T", "kind": "k", "duration_hours": 1, "vessel": "zz"}]),
         "unknown vessel"),
        (campaign(tasks=[
            {"key": "t1", "name": "T", "kind": "k", "duration_hours": 1, "vessel": "a", "depends_on": ["t2"]},
            {"key": "t2", "name": "U", "kind": "k", "duration_hours": 1, "vessel": "a", "depends_on": ["t1"]},
        ]), "cycle"),
        (campaign(tasks=[
            {"key": "t1", "name": "T", "kind": "k", "duration_hours": 1, "vessel": "a", "depends_on": ["t1"]},
        ]), "itself"),
        (campaign(vessels=[{"key": "a", "name": "A", "vessel_class": "x"}, {"key": "a", "name": "B", "vessel_class": "y"}]),
         "vessel keys"),
    ],
)
def test_invalid_plans_return_422(client, body, fragment):
    r = client.post("/api/campaigns", json=body)
    assert r.status_code == 422
    assert fragment in r.text


def test_naive_start_time_rejected(client):
    r = client.post("/api/campaigns", json=campaign(start_time="2026-03-02T06:00:00"))
    assert r.status_code == 422
    assert "timezone" in r.text


def test_campaign_needs_tasks(client):
    assert client.post("/api/campaigns", json=campaign(tasks=[])).status_code == 422


@pytest.mark.parametrize(
    "query",
    [
        "INSERT DATA { <urn:a> <urn:b> <urn:c> }",
        "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
        "SELECT WHERE broken",
    ],
)
def test_sparql_rejects_updates_and_bad_syntax(client, query):
    assert client.post("/api/sparql", json={"query": query}).status_code == 400


def test_ontology_served(client):
    r = client.get("/api/ontology")
    assert r.status_code == 200
    assert "mcw:ScheduledActivity a owl:Class" in r.text


def test_extract_text_only_for_text_types():
    assert extract_text(b"hello", "text/markdown") == "hello"
    assert extract_text(b"\x89PNG", "image/png") == ""
