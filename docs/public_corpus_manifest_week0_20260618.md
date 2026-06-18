# Public Corpus Manifest: Week0 Fallback Candidates

Generated: 2026-06-18

Purpose: provide auditable public-corpus fallback candidates when internal runbook owners are unavailable. This manifest is a collection/evaluation input, not proof that every source has been imported.

## Policy

- Internal enterprise runbooks remain preferred when available.
- Public sources can be used for local RAG evaluation and corpus expansion only when source URL, license, collected date, domain, and synthetic flag are recorded.
- If license is unclear, do not import the page into the production-grade corpus. Use it only as inspiration for a separately written synthetic sample marked `synthetic=true`.
- Do not change retrieval, rerank, query rewrite, prompt, or top-k defaults from corpus collection alone.

## Candidate Sources

| ID | Domain | Source URL | License Evidence | License Status | Synthetic | Import Status | Intended Coverage |
|---|---|---|---|---|---|---|---|
| PUB-K8S-POD-LIFECYCLE | Kubernetes | https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/ | Page footer says Kubernetes documentation is distributed under CC BY 4.0 | eligible | false | candidate | Pod lifecycle, CrashLoopBackOff, readiness/liveness concepts |
| PUB-GKE-CRASHLOOP | Kubernetes / GKE | https://cloud.google.com/kubernetes-engine/docs/troubleshooting/crashloopbackoff-events | Google Cloud page footer says content is licensed under Creative Commons Attribution 4.0 unless otherwise noted | eligible | false | candidate | CrashLoopBackOff troubleshooting and event investigation |
| PUB-GCLOUD-REDIS-MEM | Redis / Memorystore | https://cloud.google.com/memorystore/docs/redis/memory-management-best-practices | Google Cloud page footer says content is licensed under Creative Commons Attribution 4.0 unless otherwise noted | eligible | false | candidate | Redis memory pressure, eviction, operational best practices |
| PUB-GCLOUD-MYSQL-CONN | MySQL / Cloud SQL | https://cloud.google.com/sql/docs/mysql/debugging-connectivity | Google Cloud page footer says content is licensed under Creative Commons Attribution 4.0 unless otherwise noted | eligible | false | candidate | MySQL connectivity and Cloud SQL troubleshooting |
| PUB-PROM-ALERTING | Prometheus | https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/ | Prometheus site footer says components are available under Apache 2.0 License | eligible-review | false | candidate | Alerting rules, labels, alert notification concepts |

## Collection Fields Required Before Import

| Field | Required | Notes |
|---|---|---|
| `source_id` | yes | Stable ID from this manifest |
| `source_url` | yes | Canonical URL |
| `license` | yes | Example: `CC-BY-4.0`, `Apache-2.0` |
| `license_evidence` | yes | Short local note of where the license was observed |
| `collected_at` | yes | ISO date/time |
| `domain` | yes | Kubernetes / Redis / MySQL / Prometheus / incident-response |
| `synthetic` | yes | `false` for copied/derived public docs, `true` for separately written synthetic docs |
| `import_decision` | yes | `candidate`, `imported`, `rejected`, `license-blocked` |
| `eval_coverage` | yes | Which eval/risk area the source is intended to cover |

## Week0 Decision

Decision: `promote manifest as fallback source list; do not import yet`

Reason:

- Sources have auditable URLs and license evidence.
- Week0's job is to establish the fallback mechanism and manifest shape.
- Actual corpus import and retrieval impact comparison belongs to Month1/Month2 compare gates.
