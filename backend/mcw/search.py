"""OpenSearch metadata index for campaign documents."""

from __future__ import annotations

import httpx

MAPPING = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "document_id": {"type": "keyword"},
            "campaign_id": {"type": "integer"},
            "campaign_name": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
            "title": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
            "filename": {"type": "keyword"},
            "content_type": {"type": "keyword"},
            "size_bytes": {"type": "long"},
            "sha256": {"type": "keyword"},
            "object_key": {"type": "keyword"},
            "tags": {"type": "keyword"},
            "uploaded_at": {"type": "date"},
            "synthetic": {"type": "boolean"},
            "text": {"type": "text"},
        }
    },
}


class SearchIndex:
    def __init__(self, url: str, index: str) -> None:
        self.http = httpx.Client(base_url=url.rstrip("/"), timeout=30)
        self.index = index

    def ensure_index(self) -> None:
        if self.http.head(f"/{self.index}").status_code == 404:
            r = self.http.put(f"/{self.index}", json=MAPPING)
            if r.status_code >= 400 and "resource_already_exists" not in r.text:
                r.raise_for_status()

    def put(self, doc: dict) -> None:
        r = self.http.put(f"/{self.index}/_doc/{doc['document_id']}", params={"refresh": "wait_for"}, json=doc)
        r.raise_for_status()

    def delete_campaign(self, campaign_id: int) -> None:
        r = self.http.post(
            f"/{self.index}/_delete_by_query",
            params={"refresh": "true"},
            json={"query": {"term": {"campaign_id": campaign_id}}},
        )
        r.raise_for_status()

    def search(self, q: str, campaign_id: int | None = None, tag: str | None = None, size: int = 20) -> list[dict]:
        must: list[dict] = []
        if q.strip():
            must.append({
                "multi_match": {
                    "query": q,
                    "fields": ["title^3", "filename^2", "tags^2", "campaign_name", "text"],
                }
            })
        filters: list[dict] = []
        if campaign_id is not None:
            filters.append({"term": {"campaign_id": campaign_id}})
        if tag:
            filters.append({"term": {"tags": tag}})
        body = {
            "size": size,
            "query": {"bool": {"must": must or [{"match_all": {}}], "filter": filters}},
            "_source": {"excludes": ["text"]},
            "highlight": {"fields": {"text": {"fragment_size": 120, "number_of_fragments": 1}}},
        }
        r = self.http.post(f"/{self.index}/_search", json=body)
        r.raise_for_status()
        hits = []
        for h in r.json()["hits"]["hits"]:
            hit = dict(h["_source"])
            hit["score"] = h["_score"]
            hit["highlight"] = (h.get("highlight", {}).get("text") or [None])[0]
            hits.append(hit)
        return hits

    def docs_for_campaign(self, campaign_id: int) -> list[dict]:
        r = self.http.post(
            f"/{self.index}/_search",
            json={"size": 1000, "query": {"term": {"campaign_id": campaign_id}}, "_source": {"excludes": ["text"]}},
        )
        r.raise_for_status()
        return [h["_source"] for h in r.json()["hits"]["hits"]]

    def ping(self) -> bool:
        return self.http.get("/_cluster/health").status_code == 200
