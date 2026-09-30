# Upasthiti Development Roadmap

**Status:** the roadmap remains planned unless marked delivered here. The working copy now includes additive student sign-in/portal/recovery/review workflows, role/class scoping, deterministic local chat, isolated Demo Mode, manual verified local backups/restores, and explicit evidence retention cleanup, in addition to QR/local-Wi-Fi upload, Smart Capture, and email workflows. Full real-device and production deployment validation remains outstanding.

**Stabilization update (2026-09-30):** staff navigation now comes from one order/role map; gallery format 2 records recognizer IDs/version identifiers and refuses unsafe matches until an atomic photo-based rebuild; student removal archives the row and preserves attendance/edit/review history. The additive student migration is covered by tests.

## Delivered Outside the Proposed Milestones

- Temporary phone-photo upload in Enrollment and Group Photos.
- Optional Gmail and Microsoft OAuth delivery, custom SMTP fallback, DPAPI-protected credentials/tokens, normalized student recipients collected during enrollment and editable later, opt-in post-save absence notifications, a class Email Center with private per-student Send/Send All, delivery history/retry, and explicit date-range reports.
- Explicit one-shot scheduled student reports; they run only while the desktop application is open, the computer is on, an administrator is logged in, and the sender is enabled.
- Laptop-side Smart Capture feedback for Group Photos, safe aggregate mobile status, completed-analysis reuse at the existing attendance review step, and targeted layout/navigation improvements. Regression testing now runs from the restored Python 3.12 venv; physical-phone verification remains outstanding.
- Student login with forced first-password change; dedicated self-only portal; deterministic attendance recovery/what-if calculations; role/class-scoped staff recovery and review queue; attendance review requests with a 30-day correction and sent-email/report 10-day request window; and offline deterministic role-aware chat. Passwords use PBKDF2-SHA256, with legacy local hashes upgraded after successful login.
- Faculty class assignments and 30-calendar-day session-date edits; transactional session saves and review edit audit; class scope in attendance, report/email and enrollment service operations. Student archiving preserves history; old gallery compatibility is guarded with an explicit rebuild path.
- Isolated disposable Demo Mode with synthetic records, no copied biometric assets and outbound mail hard-disabled; ZIP backup/restore with SQLite integrity, manifest hashes, safe paths and a pre-restore backup; admin-triggered old evidence cleanup that preserves attendance rows and sessions with active reviews; spreadsheet text formula-marker neutralization.
- OAuth app-registration onboarding and provider-side token revocation remain operational setup tasks. Disconnect removes the local credential; administrators may also need to revoke the app grant in the provider account.

## Prioritization Scale

Each item records **V**alue, **F**easibility, **C**omplexity, **Perf**ormance cost, **Priv**acy/security risk introduced, **Maint**enance cost, **Comm**ercial value, and **Priority**. Ratings use Low / Medium / High (L/M/H), except priority P0 (blocking), P1 (next), P2 (later), P3 (conditional). Higher complexity, cost, risk, and maintenance are less desirable. Estimates are planning judgments, not measurements.

## PHASE 1 — CORE RELIABILITY

1. **Version the gallery format and validate compatibility before matching.** Format 2 now stores recognizer IDs, manually bumped embedding-version identifiers, and format version; mismatches and legacy galleries block matching and offer a full photo-based rebuild. Installed weights are not hashed and must increment the configured version when replaced. V H; F H; C M; Perf L; Priv M; Maint M; Comm M; **P0 (delivered; weight provenance remains)**.
2. **Transactional attendance writes and durable file updates.** Session/attendance rows now commit in one SQLite transaction; gallery/report writes still need atomic replacement. V H; F H; C M; Perf L; Priv L; Maint M; Comm M; **P0 (partial)**. Keeps partial sessions from ordinary failures; file-write corruption remains.
3. **Safe student lifecycle and historical records.** Student archive/deactivation is implemented additively and preserves attendance/edit/review rows while removing active login, recipients, and recognition matching. Define biometric retention and reversible cleanup for old orphan records. V H; F M; C M; Perf L; Priv M; Maint M; Comm M; **P0 (partial)**.
4. **Automated tests for core calculations and migrations.** Disposable tests now cover role/time policy, recovery math, portal isolation, reviews, backup/restore, retention, and spreadsheet text handling. Recognition edge cases, gallery-version compatibility, and student lifecycle/repair migration coverage remain. V H; F H; C M; Perf L; Priv L; Maint M; Comm M; **P0 (partial)**.

## PHASE 2 — PRODUCTION QUALITY

1. **Authentication and authorization hardening.** PBKDF2 and legacy migration plus role/class-scoped services are delivered; account throttling, password recovery, and broader security review remain. V H; F M; C M; Perf L; Priv H; Maint M; Comm H; **P1 (partial)**.
2. **Student visibility and privacy controls.** Initial self-scoped student portal and evidence retention cleanup are delivered; retention is manual/admin-triggered, deletion lifecycle and consent/legal controls remain. V H; F M; C H; Perf L; Priv H; Maint H; Comm H; **P1 (partial)**.
3. **Verified local backup and restore.** Manual same-install ZIP backup/restore, hash/path/database validation, rollback backup and admin confirmation are delivered. Archives are not encrypted and protected OAuth tokens may not transfer across Windows accounts. V H; F H; C M; Perf L–M; Priv H; Maint M; Comm H; **P1 (partial)**.
4. **Supply-chain and diagnostic hygiene.** Verify model archive hashes/signatures where upstream provides them, validate archive paths, pin/document provenance, and use structured redacted logs. V H; F M; C M; Perf L; Priv M; Maint M; Comm H; **P1**.
5. **Email operations hardening.** Add token-expiry recovery tests against provider sandboxes and improve schedule outcome alerts/recovery. Keep real-provider checks manual and never store email bodies or access tokens. V M; F M; C M; Perf L; Priv M; Maint M; Comm M; **P2**.

## PHASE 3 — INTELLIGENCE

1. **Reproducible recognition evaluation and threshold calibration.** Version labelled, consented, held-out datasets; report false accepts, false rejects, detection misses, and uncertainty by condition/model, with confidence intervals and repeatable scripts. V H; F M; C H; Perf M for evaluation; Priv H; Maint H; Comm H; **P1**. Never derive accuracy claims from training/enrollment photos alone.
2. **Review prioritization and evidence display.** Expose per-model scores, detection quality, and why a decision was flagged; tune review queues using validated operating points. Keep human confirmation for uncertain or policy-required decisions. V H; F M; C M; Perf L; Priv M; Maint M; Comm M; **P2**.
3. **Resource-aware inference controls.** Measure peak RAM/latency by photo size and model set; offer safe CPU/RAM profiles, bounded image dimensions, cancellation, and staged-photo limits. V H; F H; C M; Perf L (may reduce cost); Priv L; Maint M; Comm H; **P1**.

## PHASE 4 — ORGANIZATION FEATURES

Delivered separately from this proposed roadmap: **temporary QR/local-Wi-Fi phone photo upload** for existing Enrollment and Group Photos workflows. It adds no cloud service or synchronization and does not alter attendance decisions.

1. **Institutional roster import and reconciliation.** Validate roster files, preview changes, detect duplicate IDs, and provide reversible class/student updates. V H; F H; C M; Perf L; Priv M; Maint M; Comm H; **P2**.
2. **Attendance policy and schedule configuration.** Add explicit institution/class rules (late window, excused denominator, session roster) with audit trail and migration-safe defaults. V M–H; F M; C H; Perf L; Priv M; Maint H; Comm H; **P2**.
3. **Localization and accessibility completion.** Native review for Kannada/Hindi, keyboard/focus testing, scalable layouts, and accessible error/uncertainty labels. V M; F H; C M; Perf L; Priv L; Maint M; Comm M; **P2**.

## PHASE 5 — COMMERCIAL PRODUCT

1. **Independent licensing and privacy readiness review.** Verify rights for code, each recognizer, detector, and weights; define consent, retention, incident response, and jurisdictional obligations with qualified counsel. V H; F M; C M; Perf L; Priv H; Maint M; Comm H; **P0 before sale/deployment**. UI labels are not legal clearance.
2. **Supported installer, updates, and deployment documentation.** Sign builds, validate dependencies/models, define offline update and rollback procedures, and publish hardware/support matrix after measurement. V H; F M; C H; Perf L; Priv M; Maint H; Comm H; **P2**.
3. **Operational administration and support process.** Document onboarding, account recovery, incident response, audit export, and support-safe diagnostics without copying biometric data. V M–H; F H; C M; Perf L; Priv M; Maint M; Comm H; **P2**.

## PHASE 6 — SCALE

1. **Multi-device/site synchronization (only if validated demand exists).** First define authoritative records, conflict resolution, offline behavior, encryption/key management, tenant isolation, and biometric data minimization; prototype with synthetic data before any live migration. V H; F L–M; C H; Perf H; Priv H; Maint H; Comm H; **P3**. It changes the current local-only threat model and should not precede security and backup foundations.
2. **Large-roster performance architecture.** Profile representative class sizes first; only then consider indexed/vectorized search or a separate inference worker. V M–H; F M; C H; Perf M–H; Priv M; Maint H; Comm M–H; **P3** pending measured bottleneck.

## Delivery Gates

- Do not begin feature work until scope and policy choices are approved and production-data impact is understood.
- For data-format or database changes, provide migration, backup, rollback, and disposable-copy verification before rollout.
- For recognition changes, report dataset provenance, operating conditions, error tradeoffs, uncertainty, and resource measurements; do not promise accuracy without measured results.
- For commercial deployment, complete independent licensing/privacy review and verify packaged-model provenance before release.

## Current Validation Snapshot (2026-09-30)

- Python 3.12.14: `pip check` passed and `compileall -q app tests` passed.
- Full suite: **68 passed, 0 failed, 0 errors, 0 skipped**, including Tk UI and DPAPI tests in the verified Windows process context.
- Tk/Tcl 8.6.12 and Tk 8.6.12 root creation passed with explicit library paths. The restricted sandbox process could not initialize Tcl/DPAPI; no application workaround or plaintext fallback was added.
- Tests used temporary databases and synthetic vectors/images. No production attendance data was changed, and `C:\Upasthiti` was not accessed.
- No real attendance records or external mail were used in these tests. Real model inference, phone/Wi-Fi interoperability, visual review at varied scaling, cross-Windows-user restore, and legal/licensing review remain manual gates.
- Manual retention cleanup and manual backups are available; neither is scheduled automatically. Backups are not encrypted.
