"""FastAPI application."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse, Response
from rdflib.plugins.sparql import prepareQuery
from sqlalchemy.orm import Session

from .config import Settings
from .fixture_check import check_campaign, ensure_fixture, fixture_spec
from .rdf import campaign_graph
from .schemas import CampaignIn, CampaignOut, CampaignSummary, DocumentOut, SparqlIn
from .service import InvalidPlan, NotFound, Workbench

ALLOWED_QUERY_FORMS = {"SelectQuery", "AskQuery"}


def create_app(workbench: Workbench | None = None, initialise: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if initialise:
            app.state.wb.initialise()
        yield

    app = FastAPI(title="Maritime Campaign Workbench", version="0.1.0", lifespan=lifespan)
    app.state.wb = workbench or Workbench.from_settings(Settings())

    def wb(request: Request) -> Workbench:
        return request.app.state.wb

    def session(request: Request) -> Iterator[Session]:
        yield from request.app.state.wb.db.session()

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, exc: NotFound):
        return PlainTextResponse(str(exc), status_code=404)

    @app.exception_handler(InvalidPlan)
    async def _invalid(_: Request, exc: InvalidPlan):
        return PlainTextResponse(str(exc), status_code=422)

    @app.get("/api/health")
    def health(w: Workbench = Depends(wb)) -> dict:
        status = {}
        for name, probe in (
            ("postgres", lambda: w.db.engine.connect().close() is None),
            ("minio", w.store.ping),
            ("opensearch", w.index.ping),
            ("fuseki", w.fuseki.ping),
        ):
            try:
                status[name] = bool(probe())
            except Exception:  # noqa: BLE001 - health reports any failure as down
                status[name] = False
        return {"ok": all(status.values()), "services": status}

    @app.get("/api/campaigns", response_model=list[CampaignSummary])
    def list_campaigns(w: Workbench = Depends(wb), s: Session = Depends(session)):
        return w.list_campaigns(s)

    @app.post("/api/campaigns", response_model=CampaignOut, status_code=201)
    def create_campaign(body: CampaignIn, w: Workbench = Depends(wb), s: Session = Depends(session)):
        return w.to_dict(w.create_campaign(s, body))

    @app.get("/api/campaigns/{campaign_id}", response_model=CampaignOut)
    def get_campaign(campaign_id: int, w: Workbench = Depends(wb), s: Session = Depends(session)):
        return w.to_dict(w.load(s, campaign_id))

    @app.delete("/api/campaigns/{campaign_id}", status_code=204)
    def delete_campaign(campaign_id: int, w: Workbench = Depends(wb), s: Session = Depends(session)):
        w.delete_campaign(s, campaign_id)

    @app.get("/api/campaigns/{campaign_id}/rdf")
    def campaign_rdf(campaign_id: int, w: Workbench = Depends(wb), s: Session = Depends(session)):
        g = campaign_graph(w.load(s, campaign_id))
        return Response(g.serialize(format="turtle"), media_type="text/turtle")

    @app.post("/api/campaigns/{campaign_id}/documents", response_model=DocumentOut, status_code=201)
    async def upload_document(
        campaign_id: int,
        file: UploadFile = File(...),
        title: str = Form(""),
        tags: str = Form(""),
        w: Workbench = Depends(wb),
        s: Session = Depends(session),
    ):
        data = await file.read()
        if not data:
            raise HTTPException(422, "empty file")
        if len(data) > w.settings.max_upload_bytes:
            raise HTTPException(413, "file too large")
        d = w.attach_document(
            s,
            campaign_id,
            title=title.strip() or (file.filename or "document"),
            filename=file.filename or "document",
            content_type=file.content_type or "application/octet-stream",
            data=data,
            tags=tags.split(","),
        )
        return {c: getattr(d, c) for c in DocumentOut.model_fields}

    @app.get("/api/documents/{document_id}/content")
    def download(document_id: str, w: Workbench = Depends(wb), s: Session = Depends(session)):
        d, data = w.get_document(s, document_id)
        return Response(
            data,
            media_type=d.content_type,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(d.filename)}"},
        )

    @app.get("/api/search")
    def search(q: str = "", campaign_id: int | None = None, tag: str | None = None, w: Workbench = Depends(wb)):
        return w.index.search(q, campaign_id=campaign_id, tag=tag)

    @app.post("/api/sparql")
    def sparql(body: SparqlIn, w: Workbench = Depends(wb)):
        try:
            form = prepareQuery(body.query).algebra.name
        except Exception as exc:  # noqa: BLE001 - any parse failure is a client error
            raise HTTPException(400, f"invalid SPARQL: {exc}") from exc
        if form not in ALLOWED_QUERY_FORMS:
            raise HTTPException(400, "only SELECT and ASK queries are accepted")
        try:
            return w.fuseki.query(body.query)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/ontology")
    def ontology(w: Workbench = Depends(wb)):
        return Response(w.settings.ontology_path.read_text(), media_type="text/turtle")

    @app.post("/api/fixture", response_model=CampaignOut)
    def load_fixture(w: Workbench = Depends(wb), s: Session = Depends(session)):
        return w.to_dict(ensure_fixture(w, s))

    @app.get("/api/campaigns/{campaign_id}/consistency")
    def consistency(campaign_id: int, w: Workbench = Depends(wb), s: Session = Depends(session)):
        c = w.load(s, campaign_id)
        spec = fixture_spec(w.settings.fixtures_dir)
        checks = check_campaign(w, c, spec if c.name == spec["name"] else None)
        return {
            "campaign_id": c.id,
            "passed": sum(x.ok for x in checks),
            "failed": sum(not x.ok for x in checks),
            "checks": [asdict(x) for x in checks],
        }

    return app


app = create_app()
