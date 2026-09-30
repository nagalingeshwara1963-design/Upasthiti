"""Validated local backup/restore for SQLite and app-owned attendance assets."""
import hashlib, json, os, shutil, sqlite3, tempfile, time, zipfile, uuid
from pathlib import Path, PurePosixPath
from . import config
from .db import DB

ASSETS = ("enroll", "galleries", "reports", "photos")
FORMAT = 1


def _digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()


def _copy_tree_safe(source, destination):
    if not source.exists(): return
    root = source.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        if path.is_symlink(): raise ValueError(f"Backup asset contains a symbolic link: {path.name}")
        resolved = path.resolve()
        if not resolved.is_relative_to(root): raise ValueError("Backup asset path escapes its data directory.")
        relative = path.relative_to(source); target = destination / relative
        if path.is_dir(): target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, target)


def create_backup(db, destination):
    """Write an atomic ZIP containing a consistent DB snapshot and app data assets."""
    destination = Path(destination).resolve(); destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="upasthiti-backup-", dir=str(destination.parent)) as tmp:
        staging = Path(tmp); db_copy = staging / "database" / "upasthiti.db"; db_copy.parent.mkdir(parents=True)
        with db._lock:
            target = sqlite3.connect(str(db_copy))
            try: db.con.backup(target)
            finally: target.close()
        check = sqlite3.connect(str(db_copy))
        try:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok": raise ValueError("Database snapshot failed its integrity check.")
        finally: check.close()
        present_assets = [name for name in ASSETS if (config.DATA / name).exists()]
        for name in ASSETS:
            target = staging / "assets" / name
            if (config.DATA / name).exists(): _copy_tree_safe(config.DATA / name, target)
            else: target.mkdir(parents=True, exist_ok=True)
        files = [p for p in staging.rglob("*") if p.is_file()]
        manifest = {"format": FORMAT, "created_at": time.time(), "assets_present": present_assets, "files": {
            p.relative_to(staging).as_posix(): _digest(p) for p in sorted(files)}}
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
        tmp_zip = destination.with_name(destination.name + ".tmp")
        try:
            with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.write(manifest_path, "manifest.json")
                for path in files: archive.write(path, path.relative_to(staging).as_posix())
            with zipfile.ZipFile(tmp_zip) as archive: _validate_archive(archive, verify_hashes=True)
            os.replace(tmp_zip, destination)
        finally:
            try: tmp_zip.unlink(missing_ok=True)
            except OSError: pass
    return destination


def _validate_archive(archive, verify_hashes):
    infos = archive.infolist(); names = set(); total = 0
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        mode = (info.external_attr >> 16) & 0xFFFF
        if path.is_absolute() or ".." in path.parts or "\\" in name or (mode & 0o170000) == 0o120000:
            raise ValueError("Backup contains an unsafe archive path.")
        if name in names: raise ValueError("Backup contains duplicate archive entries.")
        names.add(name); total += info.file_size
        if total > 10 * 1024**3: raise ValueError("Backup archive exceeds the 10 GiB safety limit.")
        if name != "manifest.json" and not (name == "database/upasthiti.db" or any(name.startswith(f"assets/{a}/") for a in ASSETS)):
            raise ValueError("Backup contains an unsupported file.")
    if "manifest.json" not in names or "database/upasthiti.db" not in names:
        raise ValueError("Backup is missing its manifest or database.")
    manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    if manifest.get("format") != FORMAT or set(manifest.get("files", {})) != names - {"manifest.json"}:
        raise ValueError("Backup format or manifest contents are invalid.")
    if verify_hashes:
        for name, expected in manifest["files"].items():
            h = hashlib.sha256()
            with archive.open(name) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""): h.update(block)
            if h.hexdigest() != expected:
                raise ValueError("Backup checksum mismatch.")
    return manifest


def validate_backup(source):
    with zipfile.ZipFile(source, "r") as archive:
        manifest = _validate_archive(archive, verify_hashes=True)
        with tempfile.TemporaryDirectory(prefix="upasthiti-validate-") as tmp:
            db_path = Path(tmp) / "upasthiti.db"
            with archive.open("database/upasthiti.db") as src, open(db_path, "wb") as dst: shutil.copyfileobj(src, dst)
            con = sqlite3.connect(str(db_path))
            try:
                if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok": raise ValueError("Backup database failed its integrity check.")
                tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {"classes", "students", "sessions", "attendance"}.issubset(tables): raise ValueError("Backup database is missing core Upasthiti tables.")
            finally: con.close()
        return {"created_at": manifest["created_at"], "file_count": len(manifest["files"]), "valid": True}


def restore_backup(db, source):
    """Apply only after validation; save a rollback copy before any target is moved.

    The caller must stop workers and replace its DB/service objects with the returned DB.
    """
    validate_backup(source)
    config.ensure_dirs()
    parent = config.DATA.parent
    rollback_path = config.BACKUP_DIR / f"pre_restore_{int(time.time())}_{uuid.uuid4().hex[:8]}.zip"
    create_backup(db, rollback_path)
    with tempfile.TemporaryDirectory(prefix="upasthiti-restore-", dir=str(parent)) as tmp:
        stage = Path(tmp) / "staged"; stage.mkdir()
        with zipfile.ZipFile(source, "r") as archive:
            manifest = _validate_archive(archive, verify_hashes=True)
            for info in archive.infolist():
                if info.is_dir() or info.filename == "manifest.json": continue
                target = stage.joinpath(*PurePosixPath(info.filename).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, open(target, "wb") as dst: shutil.copyfileobj(src, dst)
        for name in ASSETS: (stage / "assets" / name).mkdir(parents=True, exist_ok=True)
        staged_db = stage / "database" / "upasthiti.db"
        current_data = config.DATA
        hold = Path(tmp) / "previous"; hold.mkdir()
        targets = [(config.DB_PATH, staged_db, hold / "upasthiti.db")]
        for name in ASSETS:
            staged = stage / "assets" / name
            targets.append((current_data / name, staged, hold / name))
        db.con.close()
        moved, installed = [], []
        try:
            for target, replacement, previous in targets:
                if target.exists(): os.replace(target, previous); moved.append((target, previous))
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(replacement, target); installed.append(target)
            return DB(config.DB_PATH)
        except Exception:
            for target in reversed(installed):
                try:
                    if target.is_dir(): shutil.rmtree(target)
                    else: target.unlink(missing_ok=True)
                except OSError: pass
            for target, previous in reversed(moved):
                try:
                    if previous.exists(): os.replace(previous, target)
                except OSError: pass
            DB(config.DB_PATH).con.close()
            raise
