# 05 · Risks and permissions

## Licensing: permission granted (2026-11-02)
The user reported on 2026-11-02 that the owner (adnanf787) granted permission. Keep the owner's written message as evidence. The original analysis follows.

### Original finding
The reference repository has **no LICENSE file and no license statement**. Under default copyright, public visibility does not grant permission to copy, modify or redistribute.

Current handling:
- The backend is copied **locally** into this private working tree to build and test the new frontend. Nothing has been pushed, published or deployed.
- `ATTRIBUTION.md` credits the original author and lists exactly which files are reused.
- **Required before any public GitHub push, Vercel deployment or academic submission containing the backend:** written permission from the repository owner (`adnanf787`), ideally by adding a license (e.g. MIT) to the original repo or a dated written message the user can keep. Once received, record it in `ATTRIBUTION.md`.
- If permission is refused, the original frontend, documentation and analysis in this repo remain the user's own work, but the backend must be removed or rewritten independently.

## Other risks
| Risk | Severity | Mitigation |
|---|---|---|
| Spark needs a Java runtime on each new machine | Low | Unzip Temurin 17 JRE into `.runtime/` (verified SHA-256) or set `JAVA_HOME`; `npm run dev` auto-detects |
| Windows publication race in benchmark engine | High for Windows users (silent incomplete results) | Fixed with test (08); frontend also labels any non-terminal engine "incomplete" |
| Synthetic results mistaken for real performance | High (academic integrity) | Synthetic badges on every screen, warnings, methodology |
| Hosted Basic auth is single-owner, not multi-user | Medium | Documented; no claim of RBAC |
| NVIDIA provider not verified | Low (optional) | Main app requires no key |
| Brand "SignalSpend AI" trademark availability | Low | Working name only; **not checked** |
| Backend `WWW-Authenticate` realm still says "Adwise" | Cosmetic | Protected backend; the Next.js proxy (first prompt seen) uses "SignalSpend" |
