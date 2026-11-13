"""Workbench service: Postgres is the system of record; MinIO, OpenSearch and
Fuseki are written after each successful Postgres commit."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .config import Settings
from .db import Database
from .models import Campaign, Document, ScheduleEntry, Task, Vessel
from .rdf import Fuseki, campaign_graph, campaign_graph_iri
from .scheduler import PlanTask, PlanVessel, ScheduleError, build_schedule
from .schemas import CampaignIn
from .search import SearchIndex
from .storage import DocumentStore

TEXT_TYPES = ("text/", "application/json", "application/xml", "application/x-yaml")
SYNTHETIC_TAG = "synthetic"


class NotFound(LookupError):
    pass


class InvalidPlan(ValueError):
    pass


def object_prefix(campaign_id: int) -> str:
    return f"campaigns/{campaign_id}/"


def extract_text(data: bytes, content_type: str) -> str:
    """Searchable text for text-like documents; binary files are indexed by metadata only."""
    if not content_type.startswith(TEXT_TYPES):
        return ""
    return data.decode("utf-8", errors="replace")[:200_000]


@dataclass
class Workbench:
    db: Database
    store: DocumentStore
    index: SearchIndex
    fuseki: Fuseki
    settings: Settings

    @classmethod
    def from_settings(cls, s: Settings) -> Workbench:
        return cls(
            db=Database(s.database_url),
            store=DocumentStore(s.minio_endpoint, s.minio_access_key, s.minio_secret_key, s.minio_bucket),
            index=SearchIndex(s.opensearch_url, s.opensearch_index),
            fuseki=Fuseki(s.fuseki_url, s.fuseki_dataset, s.fuseki_user, s.fuseki_password),
            settings=s,
        )

    def initialise(self) -> None:
        self.db.create_schema()
        self.store.ensure_bucket()
        self.index.ensure_index()
        self.fuseki.ensure_dataset()
        self.fuseki.load_ontology(self.settings.ontology_path)

    # ---- reads -------------------------------------------------------------

    def load(self, s: Session, campaign_id: int) -> Campaign:
        c = s.scalars(
            select(Campaign)
            .where(Campaign.id == campaign_id)
            .options(
                selectinload(Campaign.vessels),
                selectinload(Campaign.tasks).selectinload(Task.depends_on),
                selectinload(Campaign.schedule),
                selectinload(Campaign.documents),
            )
        ).one_or_none()
        if c is None:
            raise NotFound(f"campaign {campaign_id} not found")
        return c

    def list_campaigns(self, s: Session) -> list[dict]:
        def count(model):
            return (
                select(func.count()).where(model.campaign_id == Campaign.id).correlate(Campaign).scalar_subquery()
            )

        rows = s.execute(
            select(Campaign, count(Vessel), count(Task), count(Document)).order_by(Campaign.id.desc())
        ).all()
        return [
            {
                "id": c.id,
                "name": c.name,
                "start_time": c.start_time,
                "synthetic": c.synthetic,
                "vessel_count": nv,
                "task_count": nt,
                "document_count": nd,
            }
            for c, nv, nt, nd in rows
        ]

    @staticmethod
    def to_dict(c: Campaign) -> dict:
        slots = [(e.start, e.end) for e in c.schedule]
        span = (max(e for _, e in slots) - c.start_time).total_seconds() / 3600 if slots else 0.0
        return {
            "id": c.id,
            "name": c.name,
            "objective": c.objective,
            "start_time": c.start_time,
            "synthetic": c.synthetic,
            "makespan_hours": round(span, 4),
            "vessels": [
                {
                    "id": v.id,
                    "name": v.name,
                    "vessel_class": v.vessel_class,
                    "home_port": v.home_port,
                    "turnaround_hours": v.turnaround_hours,
                }
                for v in c.vessels
            ],
            "tasks": [
                {
                    "id": t.id,
                    "name": t.name,
                    "kind": t.kind,
                    "duration_hours": t.duration_hours,
                    "vessel_id": t.vessel_id,
                    "depends_on": [d.id for d in t.depends_on],
                }
                for t in c.tasks
            ],
            "schedule": [
                {"task_id": e.task_id, "vessel_id": e.vessel_id, "start": e.start, "end": e.end} for e in c.schedule
            ],
            "documents": [
                {
                    "id": d.id,
                    "title": d.title,
                    "filename": d.filename,
                    "content_type": d.content_type,
                    "size_bytes": d.size_bytes,
                    "sha256": d.sha256,
                    "object_key": d.object_key,
                    "tags": d.tags,
                    "uploaded_at": d.uploaded_at,
                }
                for d in c.documents
            ],
        }

    # ---- writes ------------------------------------------------------------

    def create_campaign(self, s: Session, data: CampaignIn) -> Campaign:
        vessel_keys = [v.key for v in data.vessels]
        task_keys = [t.key for t in data.tasks]
        if len(set(vessel_keys)) != len(vessel_keys):
            raise InvalidPlan("vessel keys must be unique")
        if len(set(task_keys)) != len(task_keys):
            raise InvalidPlan("task keys must be unique")
        for t in data.tasks:
            if t.vessel not in vessel_keys:
                raise InvalidPlan(f"task '{t.key}' references unknown vessel '{t.vessel}'")
            for d in t.depends_on:
                if d not in task_keys:
                    raise InvalidPlan(f"task '{t.key}' depends on unknown task '{d}'")
                if d == t.key:
                    raise InvalidPlan(f"task '{t.key}' depends on itself")

        # Plan before touching the database so cyclic plans are rejected cleanly.
        v_index = {k: i for i, k in enumerate(vessel_keys)}
        t_index = {k: i for i, k in enumerate(task_keys)}
        try:
            build_schedule(
                data.start_time,
                [PlanVessel(i, v.turnaround_hours) for i, v in enumerate(data.vessels)],
                [
                    PlanTask(i, v_index[t.vessel], t.duration_hours, tuple(t_index[d] for d in t.depends_on))
                    for i, t in enumerate(data.tasks)
                ],
            )
        except ScheduleError as exc:
            raise InvalidPlan(str(exc)) from exc

        c = Campaign(name=data.name, objective=data.objective, start_time=data.start_time, synthetic=True)
        s.add(c)
        vessels = {}
        for v in data.vessels:
            vessels[v.key] = Vessel(
                campaign=c,
                name=v.name,
                vessel_class=v.vessel_class,
                home_port=v.home_port,
                turnaround_hours=v.turnaround_hours,
            )
        s.add_all(vessels.values())
        s.flush()
        tasks = {}
        for t in data.tasks:
            tasks[t.key] = Task(
                campaign=c, name=t.name, kind=t.kind, duration_hours=t.duration_hours, vessel=vessels[t.vessel]
            )
        s.add_all(tasks.values())
        s.flush()
        for t in data.tasks:
            tasks[t.key].depends_on = [tasks[d] for d in t.depends_on]
        s.flush()
        self._replan(s, c)
        s.commit()
        c = self.load(s, c.id)
        self.sync_rdf(c)
        return c

    def _replan(self, s: Session, c: Campaign) -> None:
        for e in list(c.schedule):
            s.delete(e)
        s.flush()
        slots = build_schedule(
            c.start_time,
            [PlanVessel(v.id, v.turnaround_hours) for v in c.vessels],
            [PlanTask(t.id, t.vessel_id, t.duration_hours, tuple(d.id for d in t.depends_on)) for t in c.tasks],
        )
        c.schedule = [
            ScheduleEntry(campaign=c, task_id=sl.task_id, vessel_id=sl.vessel_id, start=sl.start, end=sl.end)
            for sl in slots
        ]
        s.flush()

    def attach_document(
        self, s: Session, campaign_id: int, *, title: str, filename: str, content_type: str, data: bytes, tags: list[str]
    ) -> Document:
        c = self.load(s, campaign_id)
        doc_id = str(uuid.uuid4())
        safe_name = filename.replace("/", "_").replace("\\", "_") or "document"
        key = f"{object_prefix(c.id)}documents/{doc_id}/{safe_name}"
        digest = hashlib.sha256(data).hexdigest()
        all_tags = sorted({*(t.strip() for t in tags if t.strip()), SYNTHETIC_TAG})
        self.store.put(
            key,
            data,
            content_type,
            {"sha256": digest, "campaign-id": str(c.id), "document-id": doc_id, "synthetic": "true"},
        )
        d = Document(
            id=doc_id,
            campaign=c,
            title=title,
            filename=safe_name,
            content_type=content_type,
            size_bytes=len(data),
            sha256=digest,
            object_key=key,
            tags=all_tags,
        )
        s.add(d)
        s.commit()
        s.refresh(d)
        self.index.put(
            {
                "document_id": d.id,
                "campaign_id": c.id,
                "campaign_name": c.name,
                "title": d.title,
                "filename": d.filename,
                "content_type": d.content_type,
                "size_bytes": d.size_bytes,
                "sha256": d.sha256,
                "object_key": d.object_key,
                "tags": d.tags,
                "uploaded_at": d.uploaded_at.isoformat(),
                "synthetic": True,
                "text": extract_text(data, content_type),
            }
        )
        s.expire_all()
        self.sync_rdf(self.load(s, c.id))
        return d

    def get_document(self, s: Session, document_id: str) -> tuple[Document, bytes]:
        d = s.get(Document, document_id)
        if d is None:
            raise NotFound(f"document {document_id} not found")
        return d, self.store.get(d.object_key)

    def delete_campaign(self, s: Session, campaign_id: int) -> None:
        c = self.load(s, campaign_id)
        s.delete(c)
        s.commit()
        self.store.delete_prefix(object_prefix(campaign_id))
        self.index.delete_campaign(campaign_id)
        self.fuseki.delete_graph(campaign_graph_iri(campaign_id))

    def sync_rdf(self, c: Campaign) -> None:
        self.fuseki.put_graph(campaign_graph_iri(c.id), campaign_graph(c))
