# Repository Guidelines

## Scope and Project Structure

Work only in this repository. Upasthiti is a local Windows Python desktop app; `app/launch.py` starts the UI, `app/ui/` contains CustomTkinter pages, `app/engine/` contains detection, embedding, matching, and image-quality code, and `app/services.py` connects the UI and engine. SQLite persistence is in `app/db.py`; reports and exports are in `app/reports.py`, `app/reportstore.py`, and `app/exports.py`. `data/` contains private runtime records and biometric data. Do not inspect or edit the original `C:\Upasthiti`; do not commit `data/`, `venv/`, caches, downloaded weights, or real student photos.

## Development and Run Commands

- `Setup_Upasthiti.bat` creates the virtual environment, installs `requirements.txt`, and downloads model weights. It requires internet and substantial disk space.
- `Start_Upasthiti.bat` launches `venv\Scripts\python.exe -m app.launch`.
- `Start_Upasthiti_debug.bat` keeps startup diagnostics visible in the console.
- `venv\Scripts\python.exe -m app.tools.benchmark manifest.json balanced` measures recognition behavior on explicitly labelled sample photos; see the manifest schema in `app/tools/benchmark.py`.

## Engineering Practices

Use four spaces, `snake_case` for Python modules/functions/variables, and `PascalCase` for classes. Keep UI, engine, persistence, and mail responsibilities in their existing modules. Preserve offline-first behavior, existing SQLite compatibility, and low-memory operation. Enforce student and faculty class scope in services, not only navigation. Student services derive identity from the authenticated session; never accept a frontend student ID as authority. Keep face images, embeddings, passwords, email credentials/tokens, and personal data out of source, logs, screenshots, message-body history, and fixtures. Chat must remain deterministic/local unless an explicitly approved local model is added; never send attendance data to a cloud model. Student email payloads must be generated from one identified student; Send All creates separate deliveries. Email tests must mock providers or use loopback only. Keep test databases in temporary directories. Schedules are opt-in and desktop-only. Do not claim model accuracy or commercial rights without evidence. Run `venv\Scripts\python.exe -m unittest discover -s tests -v`; UI and Windows DPAPI checks need the supported Windows environment. Never alter production attendance records to test a change.

## Data, Security, and Changes

Application state lives beneath `data/`; treat database, galleries, reports, backups, and photos as sensitive. Demo data must use its own temporary root and refuse outbound email. Phone-upload sessions must remain short-lived, size-bounded, restricted to private network interfaces, and must not log tokens, filenames, or image contents. Retention may remove only old group-photo evidence, not attendance rows; preserve evidence while review requests are active. Backups must be integrity-checked, path-validated, and leave a pre-restore snapshot. Changes to schemas or gallery formats require a compatibility/migration plan and documentation. Review deletion and export behavior for historical-data impact and spreadsheet formula injection. There is no confirmed commit convention available in this checkout; use concise imperative subjects such as `Preserve history when removing a student`. Pull requests should describe behavior and risk, list verification, and include UI screenshots when relevant. Update `PROJECT_STATUS.md`, `PLANS.md`, and `README.txt` when architecture or limitations change.
