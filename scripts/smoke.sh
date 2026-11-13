#!/usr/bin/env bash
# End-to-end smoke test of the running stack through the UI's nginx proxy.
# Creates a synthetic campaign, attaches a document, searches for it in
# OpenSearch, queries Fuseki via SPARQL, runs the cross-service check on it and
# on the fixture campaign, then deletes the smoke campaign.
set -euo pipefail
BASE="${1:-http://localhost:18480}"
MARKER="smoke$(date +%s)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {'d': d}))" "$1"; }

curl -fsS "$BASE/" | grep -q "Maritime Campaign Workbench" && echo "ui: index served"
curl -fsS "$BASE/api/health" | json "d['ok']" | grep -qx True && echo "health: all four services up"

cat > "$TMP/campaign.json" <<EOF
{"name": "SYNTHETIC smoke $MARKER", "objective": "synthetic smoke test",
 "start_time": "2026-04-01T00:00:00+00:00",
 "vessels": [{"key": "a", "name": "MV Smoke A $MARKER", "vessel_class": "survey", "turnaround_hours": 1},
             {"key": "b", "name": "MV Smoke B $MARKER", "vessel_class": "tug"}],
 "tasks": [{"key": "s", "name": "Survey", "kind": "survey", "duration_hours": 3, "vessel": "a"},
           {"key": "t", "name": "Tow", "kind": "tow", "duration_hours": 2, "vessel": "b", "depends_on": ["s"]},
           {"key": "r", "name": "Resurvey", "kind": "survey", "duration_hours": 1, "vessel": "a", "depends_on": ["t"]}]}
EOF
curl -fsS -H 'Content-Type: application/json' -d @"$TMP/campaign.json" "$BASE/api/campaigns" > "$TMP/c.json"
CID="$(json "d['id']" < "$TMP/c.json")"
echo "campaign $CID created, makespan $(json "d['makespan_hours']" < "$TMP/c.json") h, $(json "len(d['schedule'])" < "$TMP/c.json") slots"

echo "Synthetic smoke notice $MARKER for fictional anchorage." > "$TMP/notice.txt"
curl -fsS -F "file=@$TMP/notice.txt;type=text/plain" -F "title=Smoke notice" -F "tags=smoke" \
  "$BASE/api/campaigns/$CID/documents" > "$TMP/d.json"
DOC="$(json "d['id']" < "$TMP/d.json")"
echo "document $DOC stored at $(json "d['object_key']" < "$TMP/d.json")"
curl -fsS "$BASE/api/documents/$DOC/content" | cmp -s - "$TMP/notice.txt" && echo "minio: downloaded bytes identical"

HITS="$(curl -fsS "$BASE/api/search?q=$MARKER" | json "[h['document_id'] for h in d]")"
[ "$HITS" = "['$DOC']" ] && echo "opensearch: full-text search finds the document"

Q="PREFIX mcw: <https://github.com/MaheshBhushan/maritime-campaign-workbench/ontology#> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> SELECT ?task WHERE { ?a mcw:inCampaign <https://github.com/MaheshBhushan/maritime-campaign-workbench/data/campaign/$CID> ; mcw:schedulesTask ?t . ?t rdfs:label ?task } ORDER BY ?task"
TASKS="$(python3 -c 'import json,sys; print(json.dumps({"query": sys.argv[1]}))' "$Q" \
  | curl -fsS -H 'Content-Type: application/json' -d @- "$BASE/api/sparql" \
  | json "[b['task']['value'] for b in d['results']['bindings']]")"
[ "$TASKS" = "['Resurvey', 'Survey', 'Tow']" ] && echo "fuseki: SPARQL returns the scheduled tasks $TASKS"

R="$(curl -fsS "$BASE/api/campaigns/$CID/consistency")"
echo "consistency (smoke campaign): $(echo "$R" | json "d['passed']") passed, $(echo "$R" | json "d['failed']") failed"
[ "$(echo "$R" | json "d['failed']")" = 0 ]

FID="$(curl -fsS -X POST "$BASE/api/fixture" | json "d['id']")"
R="$(curl -fsS "$BASE/api/campaigns/$FID/consistency")"
echo "consistency (fixture campaign $FID): $(echo "$R" | json "d['passed']") passed, $(echo "$R" | json "d['failed']") failed"
[ "$(echo "$R" | json "d['failed']")" = 0 ]

curl -fsS -X DELETE "$BASE/api/campaigns/$CID"
[ "$(curl -fsS "$BASE/api/search?q=$MARKER" | json "len(d)")" = 0 ] && echo "delete: campaign removed from all stores"
echo "smoke: OK"
