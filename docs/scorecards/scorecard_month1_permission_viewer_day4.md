# Scorecard: Month1 Permission Viewer Day4

Scorecard ID: `SCORE-M1-PERMISSION-VIEWER-DAY4-20260618`

Date: `2026-06-18`

Owner: `Codex`

Phase: `Month1 Week2 Day4`

Module: `frontend / permissions`

## Scope

Implement a frontend-only `PermissionViewer` for the existing `我的权限` modal. The viewer classifies already granted, requestable, and forbidden capabilities from data the page already loads.

Out of scope:

- new backend permission APIs
- changing `PermissionService`, grant rules, or request review workflow
- changing RAG retrieval, rerank, query rewrite, embedding, or top_k defaults
- live permission audit quality proof

## Criteria

| Dimension | Metric / Check | Target | Evidence | Result |
|---|---|---:|---|---|
| Functionality | `PermissionViewer` static resource exists | pass | `static/js/permission-viewer.js` | pass |
| Functionality | script loads before `app.js` | pass | `static/index.html` | pass |
| Functionality | granted/requestable/forbidden classification | pass | frontend contract + browser smoke | pass |
| Functionality | requestable cards expose request action | pass | browser smoke | pass |
| Functionality | knowledge-base request pre-fills quick form | pass | browser smoke | pass |
| Functionality | tool request pre-fills advanced form | pass | browser smoke | pass |
| Regression | existing permission request forms remain | pass | frontend contract | pass |
| Regression | database confirmations section remains | pass | frontend contract | pass |
| Safety | no backend permission authority change | pass | frontend-only code diff | pass |
| Browser | no error cards / console errors | pass | `browser_smoke_result.json` | pass |

## Candidate Options

| Candidate | Description | Expected Benefit | Risk | Status |
|---|---|---|---|---|
| backend_capabilities_api | add a new `/users/{id}/capabilities` API | clean payload for UI | widens backend surface and duplicates profile/resources data | rejected |
| static_explanatory_panel | hard-code capability text in modal | fast | stale and not permission-aware | rejected |
| frontend_profile_resource_viewer | classify existing profile/resources payloads | minimal, reuses current backend contracts | frontend remains explanatory, not authoritative | promoted |

## Gate Decision

Decision: `pass`

Reason:

- Three color-state groups render from existing profile/resource data.
- Request buttons prefill existing forms instead of introducing a new request path.
- Existing request and database confirmation surfaces are preserved.
- No backend permission semantics or RAG defaults changed.

Required follow-up:

- Run Month1 Week2 Day5 acceptance gate across AIOps visualizer and permission viewer evidence.
