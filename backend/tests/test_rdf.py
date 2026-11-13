from datetime import UTC, datetime, timedelta

from rdflib import OWL, RDF, Graph

from mcw.config import Settings
from mcw.models import Campaign, Document, ScheduleEntry, Task, Vessel
from mcw.rdf import MCW, campaign_graph, campaign_iri

T0 = datetime(2026, 3, 2, 6, tzinfo=UTC)


def sample_campaign() -> Campaign:
    c = Campaign(id=7, name="SYNTHETIC test", objective="synthetic", start_time=T0, synthetic=True)
    v1 = Vessel(id=1, campaign_id=7, name="MV One", vessel_class="survey", home_port="Port A", turnaround_hours=1.5)
    v2 = Vessel(id=2, campaign_id=7, name="MV Two", vessel_class="tug", home_port="Port B", turnaround_hours=0)
    t1 = Task(id=11, campaign_id=7, name="Survey", kind="survey", duration_hours=4, vessel_id=1)
    t2 = Task(id=12, campaign_id=7, name="Tow", kind="tow", duration_hours=2, vessel_id=2)
    t2.depends_on = [t1]
    c.vessels = [v1, v2]
    c.tasks = [t1, t2]
    c.schedule = [
        ScheduleEntry(id=21, campaign_id=7, task_id=11, vessel_id=1, start=T0, end=T0 + timedelta(hours=4)),
        ScheduleEntry(id=22, campaign_id=7, task_id=12, vessel_id=2, start=T0 + timedelta(hours=4),
                      end=T0 + timedelta(hours=6)),
    ]
    c.documents = [
        Document(id="d1", campaign_id=7, title="Brief", filename="b.md", content_type="text/markdown",
                 size_bytes=10, sha256="ab" * 32, object_key="campaigns/7/documents/d1/b.md", tags=["synthetic"])
    ]
    return c


def ontology() -> Graph:
    g = Graph()
    g.parse(Settings().ontology_path, format="turtle")
    return g


def test_mirror_uses_only_terms_declared_in_ontology():
    onto = ontology()
    declared = {s for s in onto.subjects(RDF.type, None) if str(s).startswith(str(MCW))}
    data = campaign_graph(sample_campaign())
    used = {p for p in data.predicates() if str(p).startswith(str(MCW))}
    used |= {o for o in data.objects(None, RDF.type) if str(o).startswith(str(MCW))}
    assert used, "mirror should use mcw terms"
    assert used <= declared, used - declared


def test_ontology_declares_classes_and_properties():
    onto = ontology()
    classes = set(onto.subjects(RDF.type, OWL.Class))
    for name in ("Campaign", "Vessel", "Task", "ScheduledActivity", "Document"):
        assert MCW[name] in classes


def test_sparql_over_mirror_and_ontology():
    g = ontology() + campaign_graph(sample_campaign())
    rows = list(g.query(
        """PREFIX mcw: <https://github.com/MaheshBhushan/maritime-campaign-workbench/ontology#>
           PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
           SELECT ?task ?vessel ?start WHERE {
             ?a a mcw:ScheduledActivity ; mcw:schedulesTask ?t ; mcw:onVessel ?v ; mcw:startTime ?start .
             ?t rdfs:label ?task . ?v rdfs:label ?vessel } ORDER BY ?start"""
    ))
    assert [(str(r.task), str(r.vessel)) for r in rows] == [("Survey", "MV One"), ("Tow", "MV Two")]

    # subclass reasoning by property path: everything that is a CampaignEntity
    n = g.query(
        """PREFIX mcw: <https://github.com/MaheshBhushan/maritime-campaign-workbench/ontology#>
           PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
           SELECT (COUNT(?e) AS ?n) WHERE { ?e a/rdfs:subClassOf* mcw:CampaignEntity }"""
    )
    assert int(next(iter(n)).n) == 2 + 2 + 2 + 1

    dep = list(g.query(
        """PREFIX mcw: <https://github.com/MaheshBhushan/maritime-campaign-workbench/ontology#>
           ASK { ?a mcw:dependsOn ?b }"""
    ))
    assert dep == [True]


def test_campaign_marked_synthetic():
    g = campaign_graph(sample_campaign())
    assert g.value(campaign_iri(7), MCW.isSynthetic).toPython() is True
