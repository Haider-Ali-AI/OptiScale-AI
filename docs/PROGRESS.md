# Progress log

## 2026-11-02 · Session 1: Phases 0–4 (commit cd86aad)
- **Phase 0 audit · Verified.** Reference `23e788e` cloned to `../reference-source` (tag `baseline-audit-2026-11-02`, local only). Baseline pytest 193/11/1. Docs 01–05. Blocker: no license in source repo.
- **Phase 1 product definition · Verified.** Sitemap, journeys, acceptance tables (06, 07). Legacy redirects.
- **Phase 2 visual system · Verified.** New Next.js frontend, Flight Deck tokens, dark + light, shell, typed adapter.
- **Phase 3 vertical slices · Verified.** All 11 screens.
- **Phase 4 added value · Verified.** Story, funnel, matrix, trust panel, Explain my KPI, scenario review, exact-paisa check, story mode.
- BC-1 backend fix.

## 2026-11-02 · Session 2: remaining items
- **Spark · Verified.** Temurin JRE 17.0.20.1 (SHA-256 checked) in `../.runtime/`; original Spark parity test now passes on Windows.
- **10M rows · Verified.** Full matrix: 4 scales × Pandas/MapReduce/Spark × 3 repeats, all parity-correct.
- **BC-2 (F-1) · Verified.** Approved by user; test-first fix.
- **T-1 · Verified.** Stale test date pinned.
- **Commerce own-CSV import + comparison builder · Verified** with fictional fixtures through the UI (8/8).
- Tests: pytest 197/9 (Windows-only)/1, ruff ✓, tsc+eslint ✓, build ✓, QA clean, E2E 10/10 + 8/8.

## Still blocked (needs the user)
- Owner's written permission or license (redistribution, GitHub push, Vercel, submission).
- GitHub/Vercel/Neon accounts for deployment.
- NVIDIA API key for the optional live explanation check.
