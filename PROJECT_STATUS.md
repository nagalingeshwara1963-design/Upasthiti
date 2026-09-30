# Upasthiti Project Status

**Review scope:** final stabilization of the development copy on 2026-09-30. `C:\Upasthiti` and live attendance data were not accessed. Automated tests use temporary databases and mocked/synthetic images. Findings distinguish verified behavior from limits and untested real-world workflows.

## A. Project Architecture

- **Product/runtime:** Python 3.10–3.12 Windows desktop application using CustomTkinter and OpenCV. `app/launch.py` catches startup failures, appends tracebacks to `data/logs/error.log`, and attempts a message box; `app/ui/main.py` creates the single-process app and event loop.
- **UI:** `app/ui/main.py` uses `STAFF_NAVIGATION` as the source for both staff page construction and visible navigation order, with role filtering. Pages live in `page_enroll.py`, `page_photos.py`, `page_attendance.py`, `page_reports.py`, `email_center.py`, and `page_misc.py` (home, settings, models, help). Worker threads handle some model/email work and post callbacks through a queue to Tk.
- **Application services:** `app/services.py` owns a cached `ModelHub`, enrollment/gallery operations, and attendance orchestration. Optional mail is handled by `app/email_service.py`, provider OAuth/API flows by `app/oauth_email.py`, and Windows DPAPI protection by `app/securestore.py`. Core modules also include `app/auth.py`, `app/config.py`, `app/db.py`, `app/stats.py`, `app/repair.py`, `app/reportstore.py`, `app/reports.py`, `app/exports.py`, and `app/i18n.py`.
- **Engine:** `app/engine/detect.py` detects faces; `models.py` loads recognizers and produces embeddings; `gallery.py` creates and searches templates; `match.py` fuses scores and assigns faces; `pipeline.py` analyzes sessions; `quality.py` checks/enhances images.
- **Storage/deployment:** `data/upasthiti.db` is SQLite; class galleries are JSON under `data/galleries/`; enrollment images are under `data/enroll/`; session artifacts/reports, logs, backups, and model weights are also intended under `data/`. Setup is driven by `Setup_Upasthiti.bat` and `setup_models.py`; start scripts invoke `python -m app.launch` from `venv`.

## B. Current Features

- Admin/faculty password login, initial-credential student sign-in with forced first password change, and first-run admin password setup.
- Class and student enrollment, bulk photo grouping, CSV ID/name assignment, adding/removing photos, duplicate-looking student warnings, student history, and non-destructive student archiving.
- Group photo import and webcam capture, image quality and duplicate-image warnings, plus three detection modes (fast, balanced, max).
- Attendance matching across selected recognizers, uncertain-match review, absence confirmation, keyboard status editing, and point-in-photo correction for detected faces.
- Session, day, and month attendance reports; Word and Excel export; attendance status changes with editor/time history; audit-log export; database/gallery consistency scan and manual repair.
- College/logo and attendance thresholds, language selection (English/Kannada/Hindi strings; translations need native review), and model selection/licence labels.
- Administrators can manually clean up old group-photo evidence; attendance rows remain and active review sessions are retained. Cleanup is not scheduled automatically.
- Enrollment and Group Photos now offer a short-lived QR/local-Wi-Fi phone photo upload that hands files into their existing import paths.
- Optional organization Gmail/Microsoft OAuth or custom SMTP sender, optional recipient collection during enrollment and admin recipient editing, default-off absence notices after final attendance save, class Email Center with monthly/semester/custom ranges, personalized one-student and separate Send All reports, optional explicit schedules, provider-acceptance/failure history, and retry.
- `app/tools/benchmark.py` evaluates labelled manifests and writes a report under `data/reports/`. It is a utility, not a checked-in test suite.

## C. Face-Recognition Pipeline

1. `Service.get_hub()` lazily loads an InsightFace SCRFD detector from the `buffalo_l` pack plus selected recognition models. ONNX Runtime selects CUDA when available, otherwise CPU. DeepFace is optional and loaded only when selected.
2. Enrollment calls `enroll_photo()`: fast detection (sizes 640/960; minimum 40 px), chooses the largest face, computes embeddings for each active recognizer, and marks multiple-face/quality conditions. Photos are grouped by average-linkage clustering on recognizer 0 embeddings (distance threshold 0.50); a user reviews IDs/groups.
3. `Gallery` stores normalized embeddings grouped by student code and recognizer. Format 2 records recognizer IDs and explicit embedding-version identifiers; the service refuses legacy, malformed, reordered, or version-mismatched galleries and offers an atomic full rebuild from saved enrollment photos. Similarity combines half the best enrolled-photo score and half the mean-photo template score.
4. Group photos use SCRFD full-image passes and overlapping tiles. Fast uses one full pass; balanced uses two full passes plus four tiles (6 detector forwards); max uses two full passes plus 4+9 tiles (15 forwards total). Face crops are embedded by every loaded recognizer; optional enhancement re-embeds flagged faces and averages the vectors.
5. Recognizer distance matrices are averaged; a Hungarian assignment limits each student to one face per photo. Configured thresholds and margin/model-disagreement flags distinguish candidate, uncertain, and unknown faces. These thresholds and UI labels are configuration/internal claims, not accuracy results independently verified in this review.

## D. Attendance Pipeline

The UI collects class, date/time, faculty, subject, period, accuracy mode, threshold mode, and staged photos. `AttendancePage` starts `Service.run_session()` on a daemon thread. `analyse_session()` checks/enhances each image, detects faces, embeds/matches, and aggregates a student as present if assigned in any photo; all others start absent. It flags weak, close-call, and model-disagreement matches as uncertain. The review dialog shows uncertain present students and absentees; the operator can select statuses, confirm, or point to an already detected face for an absent student. Saving writes the session and statuses to SQLite and boxed photos/result metadata under `data/reports/session_<id>/`. A point-in-photo correction also appends that face embedding/photo to the enrollment gallery when saved.

## E. Data Flow and Persistence

- Enrollment source photos are read locally, embedded in memory, copied as JPEGs under `data/enroll/class_<id>/`, referenced by SQLite `enroll_photos`, and represented by normalized vectors in `data/galleries/class_<id>.json`.
- Attendance group photos are staged in RAM. Analysis results enter SQLite (`sessions`, `attendance`); rendered boxed photos and a reduced JSON result are saved as report artifacts. Original group photos are not deliberately persisted by the report store, though exported reports contain boxed photos.
- Settings and password records share the SQLite `settings` table. Faculty/subject/period suggestions use `lists`; corrections use `edits`. Word/Excel exports may be saved to user-selected locations. Additive startup migrations cover attendance auto-status and student `active`/`archived_at` fields.
- Student archive marks the row inactive, removes the current matcher entry and student login/email recipients, and keeps attendance, edit, review-request/event, and enrollment-photo records. Active enrollment/attendance/email rosters exclude archived students; historical class reports can include them. Photo files remain local for policy-based cleanup or future re-enrollment.
- `photo_retention_days` is saved as a setting, but nothing in the inspected application reads it to remove photos or report artifacts.
- Storage remains local by design. Phone upload uses an ephemeral, token-protected standard-library HTTP server bound to discovered private IPv4 addresses; uploaded files are held in a temporary per-session folder under `data/phone_uploads/` and handed to the existing enrollment/group-photo workflows. The feature does not add cloud storage or an application-wide service API. Admins now have manual validated backup/restore and pre-restore rollback support; no automatic schedule is implemented.
- Email data adds `student_email_recipients` (normalized, unique per active student) and `email_deliveries` (idempotency key, recipient/context snapshot, attempt/status/timestamps, no message body). These are additive tables created on startup. Archiving removes recipient rows while retaining delivery snapshots and attendance history.
- Explicit desktop report schedules are stored in the additive `email_schedules` table with class, exact report range, send date, enabled flag, and last-run key. Due schedules are checked about once per minute only while an administrator is logged in, the app is open, and the sender is enabled. Stable per-schedule/range idempotency prevents duplicate queueing after restarts.
- Report date-range aggregation is shared through `app/stats.py`; personalized student mail consumes one student's range summary. Class workbooks use `app/reports.py` and are generated as temporary attachments only when manually requested.

## F. Security and Privacy Review

- Biometric images and embeddings, student identifiers, attendance, and reports are local but stored without application-level encryption. Filesystem/device protection and secure backups are therefore important.
- Passwords use PBKDF2-SHA256 with random salts; legacy salted SHA-256 hashes upgrade on successful login. Login has no observed throttling/lockout. Authentication is process-global and assumes a single local user at a time.
- Student portal services derive a student ID from the signed-in session. Student page construction is separate from staff pages. Faculty class access is managed by admins and checked in attendance, enrollment, review, and email/report service operations. Faculty may edit assigned-class sessions within 30 calendar days from the session date; admin keeps an override.
- SQLite schema does not declare foreign keys. New student removal archives the row and preserves attendance, edits, reviews, and reports; pre-existing orphan records can still exist and the repair tool can permanently delete them.
- `setup_models.py` downloads model archives over HTTPS and uses `ZipFile.extractall()` without a checksum/signature or explicit archive-path validation. Model/package provenance and each weight's commercial rights require independent verification before deployment or sale; UI licence labels alone are not legal clearance.
- Error paths include console `print()` and UI dialogs; only startup has a persistent traceback log. Review all diagnostic/export paths to ensure identifiers, paths, or biometric content do not leak.
- Phone-upload links are bearer tokens valid for up to 15 minutes and are invalidated when the dialog closes. Local HTTP is unencrypted, so use only a trusted private Wi-Fi network; a same-LAN observer could capture the link or image traffic. Upload count, file size, total size, dimensions, and accepted formats are bounded; the feature log omits names, tokens, and image content.
- Student recipient management and sender settings are admin-only in the UI; faculty can use the same Reports access they already have to send explicit manual reports. Student email messages are sent individually and contain one student's information only. Delivery history retains recipient/address and status metadata, not full bodies.
- Email sender/recipient administration and schedule mutation enforce administrator role in application helpers/services. Email Center listing, preview, and report submission enforce admin/faculty roles. Preview/send APIs validate that the requested student belongs to the selected class, and report bodies/counts/dates are queried using only that student ID. Send All loops those scoped APIs into one independently addressed delivery per enabled recipient.
- Gmail authorization requests `gmail.send` plus OpenID `openid email` solely to verify the signed-in sender. Gmail identity tokens are signature/audience/issuer/expiry checked against Google's published keys before sender matching; broader Gmail mailbox scopes are rejected. PKCE/loopback is used. The OAuth client ID and verified sender are in the SQLite `settings` value `email_config`; the refresh token and optional client secret are DPAPI-protected in that same config value. Access tokens remain in memory. Microsoft uses delegated Graph `Mail.Send` device-code flow. Disconnect removes local configuration, but provider-side consent may remain until separately revoked.
- Custom SMTP uses STARTTLS or SSL/TLS and a 20-second connection timeout. One serial worker sends jobs outside Tk. Provider acceptance is recorded as sent; this does not prove inbox delivery. No actual provider account was connected during validation.
- CSV/XLSX export tests verify formula-like user text is written as text. Review any new export path for the same protection.

## G. Performance Review

- Largest predictable cost is repeated SCRFD full-frame/tile inference: max mode performs 15 detector passes per image, then one embedding per face per recognizer (and a possible second pass for enhancement). Multiple large photos, recognizers, and high-resolution tiles can increase latency and peak RAM sharply.
- `ModelHub` keeps selected model objects resident; dual InsightFace networks and optional TensorFlow/DeepFace can exceed low-RAM machine budgets. All staged images remain in memory, and previews/thumbs are also generated.
- Gallery scoring stacks each student's embeddings per face/model; automatic threshold suggestion computes pairwise intra/inter-enrollment distances. These are acceptable for small classes but scale with students and enrolled photos.
- Email uses a single background worker and bounded network timeouts. Class workbooks are limited to 2 MiB to bound attachment memory use; larger workbooks must be exported manually.
- Email Center obtains class-range attendance in shared `stats` code and bulk-loads recipients, recent delivery history, and the first enrolled-photo path for display. A single serial worker keeps sending outside the UI thread. Schedules add only a lightweight once-per-minute database poll and no separate process.
- Most SQLite helper writes commit individually; attendance session and marks save in one transaction. Gallery JSON uses atomic replacement; report JSON artifacts are direct writes. No performance profiling or benchmark results were available in this review.

## H. Current Weaknesses, Technical Debt, and Limits

- Legacy gallery files lack model metadata and are rejected until rebuilt. Current format stores recognizer IDs and manually maintained embedding-version identifiers; it does not hash installed model weights, so model asset replacements must bump the corresponding version in `app/config.py`.
- Student archive preserves historical attendance/edit/review records and excludes the student from active rosters. Enrollment photos remain on disk; selective biometric/photo erasure is still a separate retention-policy operation. Repair remains destructive for genuine pre-existing orphan records.
- Local accounts use PBKDF2-SHA256; legacy salted SHA-256 account hashes upgrade after a successful login. Login throttling/account recovery and whole-disk/local-data encryption remain future work. Backups are integrity-checked but not encrypted and should be stored on a protected drive.
- Model choice is cached in memory and swapped by invalidating `hub`; no migration/re-embedding workflow is present. `deepface_available()` checks package import, not successful weight load. Setup downloads weights without integrity checks.
- Phone upload is IPv4-only and has no TLS; actual phone/browser/firewall interoperability has not been verified. Session files are temporary, but Windows may delay deletion while an image consumer still holds a file handle.
- Email provider setup requires administrator-created OAuth client registrations; provider policy can restrict Gmail API consent, Microsoft Graph permissions, SMTP, or app-password use. OAuth token revocation at the provider is not automated. Microsoft Graph attachment sending supports only the 2 MiB inline limit used here. Scheduled sends require the app open, computer powered on, an administrator logged in, and a configured sender; no Windows service/task is installed.
- Email Center supports one selected class and exact date ranges; it has no subject/faculty/department filter or configured semester calendar. A schedule is a one-shot report for a saved range/date; recurring calendar rules are not implemented. The first saved enrollment photo is used as the visual card preview; images are never attached to student mail.
- Automated tests now cover email data/service/templates/OAuth mocks and phone upload; CI, packaging/signing, a formal schema-version table, full workflow migration coverage, structured application logging, and measured performance/accuracy reports remain absent. Git history was unavailable during this review, so commit conventions could not be confirmed.
- UI contains broad exception catches and large page modules; app version is `0.1.0-engine`. No multi-user/network service or verified multi-site deployment exists. Faculty access must be explicitly assigned; new faculty have no classes until an admin maps them.
- The Settings retention cleanup is manual/admin-triggered, not automatic.
- Product descriptions mention accuracy/licensing categories, but no reproducible performance/accuracy evidence or independent license review was found. Kannada/Hindi translations explicitly request native review.

## I. Top Product Opportunities (Not Implemented)

1. **Data integrity and recoverability:** gallery/student additive migrations and safe student deactivation are delivered; atomic report-artifact writes and restore drills remain.
2. **Privacy/security baseline:** password KDF and role/class scope are delivered; login throttling, account recovery, data retention/deletion policy, and encrypted local backups remain.
3. **Recognition validity:** model/version-checked gallery format is delivered; reproducible held-out benchmark protocol, threshold calibration per model/operating condition, subgroup/error analysis, and human-review policy remain.
4. **Operational quality:** installer/model integrity validation, structured redacted logs, actionable error reporting, resource-aware inference settings, and supported hardware profile.
5. **Commercial readiness:** independent model/weight licensing and privacy/legal review, deployment documentation, support policy, and verified packaging/update mechanism.

## 22–25. Current Dependencies, Deployment, and Constraints

Required packages are NumPy, OpenCV, SciPy, ONNX Runtime, InsightFace, Pillow, CustomTkinter, python-docx, openpyxl, cryptography, and Windows-only winotify (see `requirements.txt`). DeepFace and tf-keras are optional. Setup supports Python 3.10–3.12, internet access for dependencies/weights, and a substantial model download (README estimates about 600 MB). Runtime is Windows-oriented, local/offline after setup, with CPU fallback and optional CUDA provider. Current limits include no verified low-RAM profile, no automatic scheduled backups, no demonstrated cross-device synchronization, and no independently validated accuracy or licensing claims.

## Inspection Notes

Source files inspected include launch/config/database/auth/services, all engine modules, UI pages, report/export/repair/statistics code, benchmark, dependency list, README, setup scripts, phone upload, and the email implementation. Recommendations and roadmap are in `PLANS.md`. No production records were modified.

## Earlier Baseline Snapshot (superseded)

Older inspection notes recorded Python 3.11, a missing test suite, and a different UI/runtime state. Those findings no longer describe this checkout and are omitted from the current status. The authoritative validation for this stabilization is the final section below.

## Email Product Requirements Rework Validation (2026-09-30)

Historical feature-specific verification; its test count is not the current aggregate suite result. See Final Stabilization below for authoritative validation.

The email system was extended in place. Enrollment accepts optional multiple recipients; the class Email Center uses shared range statistics and service-scoped student previews; Send All creates separate student deliveries; and opt-in schedules are checked by the desktop app. Existing sender, recipient editing, OAuth/SMTP, absence notices, QR/Wi-Fi upload, attendance, reports, and authentication remain integrated. Tests use temporary databases, mocked providers, or loopback OAuth. No real provider was connected, no email was sent, and no production attendance data was modified.

| Area | Result | Evidence / limits |
|---|---|---|
| Additive schema and enrollment recipients | **PASS** | Preserves existing students/session history; normalized multi-recipient and empty-recipient cases tested. `email_schedules` is additive. |
| Sender/recipient authorization | **PASS** | Sender configuration/removal and recipient CRUD are admin-guarded; Email Center/report service checks staff roles. |
| Student report isolation | **PASS** | Service rejects a student outside the chosen class; Send All mock test confirms each message contains only the corresponding student's information. |
| Email Center/shared attendance calculations | **PASS** | Full application construction, class summaries, actual personalized preview/template, and editable range validation tested. Enrollment photos are preview-only, never attached. |
| Absence notices/retry | **PASS** | Existing coverage verifies only final absences queue after save, no-recipient status, default-off switch, attendance persistence, and no retry of successful sends. |
| Schedule create/edit/enable/delete/due | **PASS** | Temporary DB/mock transport verifies exact range, per-student isolation, CRUD and repeat-poll idempotency. Unattended operation is not tested. |
| Existing phone upload/integration | **PASS** | Phone workflow suite and full app construction passed; no face inference or live email ran. |
| Gmail sender identity/scope safeguards | **PASS** | Editable, unauthenticated prefill; PKCE scope, local Google ID-token signature/claim verification, strict sender match, mismatch non-persistence, changed-sender invalidation, and DPAPI protected token storage covered. Real Google Cloud registration/authorization not tested. |
| Email Center date picker, search, multi-select UI | **PASS** | Controls added to the existing class-scoped screen; multi-select delegates to the existing personalized per-student delivery queue. Manual interactive clicks are not tested. |
| Automated tests and syntax | **PASS** | `venv\\Scripts\\python.exe -m unittest discover -s tests -v`: 43 tests passed; `compileall -q app tests` passed. |
| Real provider acceptance/inbox receipt | **NOT TESTED** | Requires manual OAuth registration or SMTP setup and a test mailbox. “Sent” means provider acceptance, not inbox delivery. |

The initial Gmail sender is displayed as an editable UI default, `nagalingeshwara1963@gmail.com`, only when no sender configuration exists. It is not persisted or authenticated by opening Settings. Gmail setup details live in Settings → Email and the SQLite `settings.email_config` JSON value; no downloaded credential file is required. No Google Cloud project/client was created because `gcloud` is not installed. No account was authorized and no real message was sent. To finish setup, create a Google Cloud project, enable Gmail API, configure the OAuth consent screen (including this sender as a test user while in Testing), create a Desktop app OAuth client, enter its client ID in Settings, Save, then Connect Gmail and authorize the matching account. Test mail is sent only on an explicit click.

Schedules are one-shot report jobs checked about once a minute only while the app is open, computer is on, an administrator is logged in, and sender email is configured/enabled. An overdue date is caught up at the next eligible check after reopening. Recurring calendar rules and Windows Task Scheduler integration are not implemented.

## Student Portal, Recovery, Review, Demo, and Hardening Update (2026-09-30)

Implementation stayed in the working copy. No external service or dependency version was added. Database additions are additive: student accounts, faculty-to-class assignments, recovery goals, review requests, and review event history. Session rows and marks now save in one transaction. Existing admin/faculty password hashes remain usable and upgrade to PBKDF2-SHA256 after successful login; student passwords use PBKDF2-SHA256 and first login forces a replacement password. Sessions expire after 12 hours. No failed-login throttling or password reset workflow exists yet.

Students sign in with exact name + Student ID; ambiguity across multiple students is rejected. Portal queries derive the student ID from the active authenticated session, and student UI is built separately from staff UI. The portal includes scoped home/history/date-subject-status filters, custom-period summary, recovery and what-if calculations, own review requests and notifications, profile, and local chat. Student report output is a UI summary; downloadable student-only Word/Excel reports are not implemented. Students do not see classroom evidence photos or classmates.

Recovery uses the shared `stats` status-counting policy (Present/Late count; Absent counts against attendance; Excused/OD are excluded). Empty history and impossible 100% targets are represented as not calculable. Student goals are stored per student; staff recovery is class-scoped. The assistant is deterministic and local, does not execute user SQL, and sends no information to an external AI service. No local LLM was installed or evaluated.

Review requests do not change attendance on submission. The 30-day direct-edit rule is based on the original session calendar date. A request outside that window is accepted only within 10 days of an actually successful student-specific absence notification or successful student report covering the disputed date; it is escalated and only an admin can resolve it. Failed/no-recipient/unknown delivery states do not qualify. Changes write the existing edit audit and append a review event. The queue is a local staff dashboard, not an email/push notification; search/assignment workflow polish remains.

Demo Mode uses a disposable temporary data root with only synthetic `DEMO` records, does not copy production records or model weights, and has an email service that refuses send/connect/retry/schedule actions. It demonstrates records, reports, recovery, review, and chat; actual face-recognition and phone capture require the real models and are not demonstrated there. Entering Demo Mode is blocked while production email work is active.

Admin Settings offers manual ZIP backup/restore. Backup archives contain a consistent SQLite snapshot plus enrollment photos, galleries, saved report photos/results, and local database settings; they exclude model weights, logs, and temporary phone uploads. Restore validates archive paths, checksums, and SQLite integrity, creates a timestamped pre-restore backup, then applies files with rollback on failure. Archives are not encrypted: store them only on access-controlled media. Protected OAuth credentials are Windows-user-bound and may not restore under another account. Retention cleanup is explicit/admin-triggered, removes only boxed photo/result artifacts older than the configured age, preserves attendance rows, and skips active review sessions; cleanup is not automatic.

CSV and XLSX exports now store user-controlled spreadsheet text beginning with formula markers as text. Direct UI class changes clear staged attendance/enrollment inputs to avoid cross-class reuse. The final suite includes temporary-database tests for identity isolation, Unicode login, review timing/lifecycle/audit, edit-window boundaries, backup/restore, demo email blocking, retention, spreadsheet text values, gallery compatibility/rebuild, and student archival/history reports.

### Remaining Limits

- No independent privacy/legal review, login throttling, account recovery, encrypted backups, automated backup schedule, automatic retention schedule, or cross-install absolute-path migration.
- Existing faculty users must be explicitly assigned classes. Recovery and review staff views are class-scoped but the queue lacks advanced search and request assignment/reassignment.
- Student reports are in-app summaries; student-only export is not implemented. Review event history is append-only in the application path, not tamper-proof against direct local database modification.
- Demo Mode uses synthetic marks only. It does not validate real camera, model inference, or phone/Wi-Fi capture.
- Physical phone/firewall validation, real provider mail, full ONNX inference/accuracy, model licensing, restore under a second Windows account, and visual testing at varied display scaling remain unverified.

### Prior automated validation snapshot (superseded)

Earlier 61-test and 17-test snapshots above describe prior source/runtime states and are not the current regression result. The current result is recorded in Final Stabilization below.

## Phone Upload Implementation Validation (2026-09-30)

The QR/local-Wi-Fi phone upload feature is implemented in `app/phone_upload.py` and `app/ui/phone_upload.py`, with entry points in Enrollment and Group Photos. No dependency versions changed. The test suite added in `tests/test_phone_upload.py` uses loopback networking and temporary directories only; it does not write to the live DB or attendance records.

| Area | Result | Evidence / limits |
|---|---|---|
| Upload session, routes, token, bounds, supported image validation, duplicate handling, cleanup, logging | **PASS** | 14 isolated unit tests cover session lifecycle and HTTP/image security behavior. |
| Enrollment and Group Photos integration | **PASS** | Two tests verify uploaded paths enter the pre-existing page workflow callbacks. |
| Upload dialog | **PASS** | Tk UI/QR/status test ran successfully in the test environment. |
| Application and new module import smoke check | **PASS** | `app.launch`, `app.ui.main`, and both phone-upload modules imported successfully. |
| Automated tests | **PASS** | `venv\\Scripts\\python.exe -m unittest discover -s tests -v`: 17 tests passed. |
| Actual phone, Wi-Fi adapter selection, firewall, and browser interoperability | **NOT TESTED** | Requires a separate manual phone-on-LAN check. |
| Full enrollment inference, group-photo attendance run, and ONNX inference | **NOT TESTED** | Deliberately skipped; no real biometric or attendance data was processed. |

During an early test attempt, a malformed-image request exposed Pillow's lazy plugin import calling a Tk object destructor from the HTTP worker. The implementation now preloads Pillow plugins when the upload session is created on the UI thread; the full isolated suite subsequently passed. The phone-upload server uses unencrypted local HTTP, documented in the UI and README, and must be used on a trusted private network.

## Smart Mobile Capture and UX Update (2026-09-30)

Group Photos can now run a serial, laptop-side analysis queue during an active phone upload session. It uses the configured `Service` model hub and class gallery, applies the existing `analyse_session` path one image at a time, and reuses the existing best-distance session aggregation. When all staged and received photos analyze successfully and class, mode, matching settings, model IDs, staged labels, and image identities are unchanged, Attendance opens the ordinary Review dialog from the computed result instead of repeating inference. Any analysis error or stale signature falls back to the existing full session analysis. No matching threshold or model selection was changed.

The phone page now supports photo preview, selection, remove/retake, sequential upload progress, failed-only retry, duplicate messaging, aggregate feedback, and a token-authenticated finish request. Only non-identifying counts and generic guidance are sent to the phone. Coverage is unique confidently matched students divided by enrolled class students; it is not an accuracy claim. The UI includes a phone quick action, prioritized navigation, a two-row enrollment action area, smaller review/report windows, and clearer laptop-side capture status. No dependency versions changed. Phone upload remains short-lived local HTTP and should be used only on a trusted private network.

This section describes implementation scope. Its earlier runtime/test observations are superseded. Automated mocked-worker coverage is included in the final suite below; physical phone/browser/network behavior and recognition quality/performance remain untested.

## Final Stabilization (2026-09-30)

| Check | Result | Evidence / limits |
|---|---|---|
| Python runtime | **PASS** | `venv` uses Python 3.12.14. |
| Tcl/Tk and UI initialization | **PASS** | Tcl 8.6.12/Tk 8.6.12 libraries are present; root creation and both Tk UI tests passed with explicit `TCL_LIBRARY`/`TK_LIBRARY` in the supported Windows process context. Restricted sandbox execution could not access the runtime scripts. |
| DPAPI protected storage | **PASS** | Existing native `CryptProtectData`/`CryptUnprotectData` backend round-tripped a dummy value; saved SMTP-secret test confirms the secret is absent from stored JSON and remains decryptable for the current Windows user. No plaintext fallback exists. `pywin32` is not installed or required. |
| Dependency and syntax checks | **PASS** | `pip check` and `python -m compileall -q app tests`. |
| Complete automated suite | **PASS** | **68 tests passed, 0 failures/errors, 0 skipped** with Windows Tk/DPAPI access. This count includes new gallery compatibility/rebuild and archive/migration coverage. |
| Attendance data and original project | **NOT USED** | Tests used temporary DBs and synthetic vectors/images. No production attendance records were changed; `C:\Upasthiti` was not accessed. |
| Real inference/devices/provider delivery | **NOT TESTED** | No real model inference/accuracy benchmark, phone/Wi-Fi test, external email delivery, varied display scaling, or commercial licensing review was performed. |
