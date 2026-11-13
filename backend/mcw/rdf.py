"""RDF mirror of campaign entities and the Apache Jena Fuseki client.

Each campaign is written as its own named graph so it can be replaced
atomically whenever the Postgres record changes. The checked-in ontology is
loaded into a separate named graph. The Fuseki dataset is created with
``tdb2:unionDefaultGraph true`` so plain SPARQL queries see all graphs.
"""

from __future__ import annotations

from pathlib import Path

import httpx
from rdflib import RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef

from .models import Campaign

BASE = "https://github.com/MaheshBhushan/maritime-campaign-workbench"
MCW = Namespace(f"{BASE}/ontology#")
ONTOLOGY_GRAPH = URIRef(f"{BASE}/ontology")
DATA = f"{BASE}/data/"


def campaign_iri(cid: int) -> URIRef:
    return URIRef(f"{DATA}campaign/{cid}")


def campaign_graph_iri(cid: int) -> URIRef:
    return URIRef(f"{DATA}graph/campaign/{cid}")


def vessel_iri(vid: int) -> URIRef:
    return URIRef(f"{DATA}vessel/{vid}")


def task_iri(tid: int) -> URIRef:
    return URIRef(f"{DATA}task/{tid}")


def activity_iri(sid: int) -> URIRef:
    return URIRef(f"{DATA}activity/{sid}")


def document_iri(did: str) -> URIRef:
    return URIRef(f"{DATA}document/{did}")


def _dt(value) -> Literal:
    return Literal(value.isoformat(), datatype=XSD.dateTime)


def _dec(value: float) -> Literal:
    return Literal(f"{value:.4f}", datatype=XSD.decimal)


def campaign_graph(c: Campaign) -> Graph:
    g = Graph()
    g.bind("mcw", MCW)
    ci = campaign_iri(c.id)
    g.add((ci, RDF.type, MCW.Campaign))
    g.add((ci, RDFS.label, Literal(c.name)))
    g.add((ci, MCW.objective, Literal(c.objective)))
    g.add((ci, MCW.startTime, _dt(c.start_time)))
    g.add((ci, MCW.isSynthetic, Literal(bool(c.synthetic))))

    for v in c.vessels:
        vi = vessel_iri(v.id)
        g.add((vi, RDF.type, MCW.Vessel))
        g.add((vi, RDFS.label, Literal(v.name)))
        g.add((vi, MCW.inCampaign, ci))
        g.add((vi, MCW.vesselClass, Literal(v.vessel_class)))
        g.add((vi, MCW.homePort, Literal(v.home_port)))
        g.add((vi, MCW.turnaroundHours, _dec(v.turnaround_hours)))

    for t in c.tasks:
        ti = task_iri(t.id)
        g.add((ti, RDF.type, MCW.Task))
        g.add((ti, RDFS.label, Literal(t.name)))
        g.add((ti, MCW.inCampaign, ci))
        g.add((ti, MCW.taskKind, Literal(t.kind)))
        g.add((ti, MCW.durationHours, _dec(t.duration_hours)))
        g.add((ti, MCW.assignedVessel, vessel_iri(t.vessel_id)))
        for d in t.depends_on:
            g.add((ti, MCW.dependsOn, task_iri(d.id)))

    for s in c.schedule:
        si = activity_iri(s.id)
        g.add((si, RDF.type, MCW.ScheduledActivity))
        g.add((si, MCW.inCampaign, ci))
        g.add((si, MCW.schedulesTask, task_iri(s.task_id)))
        g.add((si, MCW.onVessel, vessel_iri(s.vessel_id)))
        g.add((si, MCW.startTime, _dt(s.start)))
        g.add((si, MCW.endTime, _dt(s.end)))

    for d in c.documents:
        di = document_iri(d.id)
        g.add((di, RDF.type, MCW.Document))
        g.add((di, RDFS.label, Literal(d.title)))
        g.add((di, MCW.inCampaign, ci))
        g.add((di, MCW.contentType, Literal(d.content_type)))
        g.add((di, MCW.sizeBytes, Literal(d.size_bytes, datatype=XSD.integer)))
        g.add((di, MCW.sha256, Literal(d.sha256)))
        g.add((di, MCW.objectKey, Literal(d.object_key)))
    return g


def _assembler(dataset: str) -> str:
    return f"""@prefix fuseki: <http://jena.apache.org/fuseki#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix tdb2: <http://jena.apache.org/2016/tdb#> .

<#service> rdf:type fuseki:Service ;
    fuseki:name "{dataset}" ;
    fuseki:endpoint [ fuseki:operation fuseki:query ; fuseki:name "query" ] ;
    fuseki:endpoint [ fuseki:operation fuseki:query ; fuseki:name "sparql" ] ;
    fuseki:endpoint [ fuseki:operation fuseki:update ; fuseki:name "update" ] ;
    fuseki:endpoint [ fuseki:operation fuseki:gsp-rw ; fuseki:name "data" ] ;
    fuseki:dataset <#dataset> .

<#dataset> rdf:type tdb2:DatasetTDB2 ;
    tdb2:location "/fuseki/databases/{dataset}" ;
    tdb2:unionDefaultGraph true .
"""


class Fuseki:
    def __init__(self, url: str, dataset: str, user: str, password: str) -> None:
        self.http = httpx.Client(base_url=url.rstrip("/"), auth=(user, password), timeout=30)
        self.dataset = dataset

    def ensure_dataset(self) -> None:
        r = self.http.get(f"/$/datasets/{self.dataset}")
        if r.status_code == 200:
            return
        r = self.http.post(
            "/$/datasets", content=_assembler(self.dataset), headers={"Content-Type": "text/turtle"}
        )
        if r.status_code not in (200, 201, 409):
            raise RuntimeError(f"cannot create Fuseki dataset: {r.status_code} {r.text}")

    def put_graph(self, graph_iri: URIRef, g: Graph) -> None:
        r = self.http.put(
            f"/{self.dataset}/data",
            params={"graph": str(graph_iri)},
            content=g.serialize(format="nt"),
            headers={"Content-Type": "application/n-triples"},
        )
        r.raise_for_status()

    def delete_graph(self, graph_iri: URIRef) -> None:
        r = self.http.delete(f"/{self.dataset}/data", params={"graph": str(graph_iri)})
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    def load_ontology(self, path: Path) -> None:
        g = Graph()
        g.parse(path, format="turtle")
        self.put_graph(ONTOLOGY_GRAPH, g)

    def query(self, sparql: str) -> dict:
        r = self.http.post(
            f"/{self.dataset}/query",
            data={"query": sparql},
            headers={"Accept": "application/sparql-results+json"},
        )
        if r.status_code == 400:
            raise ValueError(r.text.strip())
        r.raise_for_status()
        return r.json()

    def ping(self) -> bool:
        return self.http.get("/$/ping").status_code == 200
