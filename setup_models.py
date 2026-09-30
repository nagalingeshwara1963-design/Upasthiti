"""Downloads the InsightFace model packs into <install>\\data\\models (about 600 MB, one
time). Run by Setup_Upasthiti.bat. Safe to run again: existing packs are kept."""
import os, sys, shutil, zipfile, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import config

NEED = {"buffalo_l": ["det_10g.onnx", "w600k_r50.onnx"],
        "antelopev2": ["glintr100.onnx", "scrfd_10g_bnkps.onnx"]}


def have(pack):
    d = config.MODELS_DIR / pack
    return all((d / f).exists() for f in NEED[pack])


def download(url, dest):
    def hook(b, bs, total):
        if total > 0:
            pct = min(100, b * bs * 100 // total)
            print(f"\r    {pct:3d}%  ({b * bs // (1024 * 1024)} MB)", end="", flush=True)
    urllib.request.urlretrieve(url, dest, hook)
    print()


def fix_nested(pack):
    d = config.MODELS_DIR / pack
    inner = d / pack
    if inner.is_dir():
        for f in inner.iterdir():
            shutil.move(str(f), str(d / f.name))
        inner.rmdir()


DEEPFACE_MODELS = ["VGG-Face", "ArcFace"]


def download_deepface_weights():
    """DeepFace only installs its code with pip; the model weights (about 600 MB) are fetched
    the first time a model is built. Do that now, so nothing is left to download later
    (for example in the middle of taking attendance, possibly with no internet).
    Returns True / False, or None if DeepFace itself is not installed."""
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    print("\n  DeepFace models (VGG-Face, ArcFace) - downloading weights, this can take a few minutes ...")
    try:
        from deepface import DeepFace
    except Exception as e:
        print(f"  [skip] DeepFace is not installed ({e}).")
        return None
    ok = True
    for name in DEEPFACE_MODELS:
        try:
            print(f"  Preparing {name} ...")
            DeepFace.build_model(name)
            print(f"  [OK]  {name}")
        except Exception as e:
            print(f"  ERROR preparing {name}: {e}")
            ok = False
    return ok


def main():
    config.ensure_dirs()
    print("\n  Upasthiti - model setup\n  Folder:", config.MODELS_DIR, "\n")
    ok = True
    for pack, url in config.MODEL_PACKS.items():
        if have(pack):
            print(f"  [OK]  {pack} already installed"); continue
        print(f"  Downloading {pack} ...")
        z = config.MODELS_DIR / f"{pack}.zip"
        try:
            download(url, z)
            with zipfile.ZipFile(z) as zf:
                zf.extractall(config.MODELS_DIR / pack)
            z.unlink(missing_ok=True)
            fix_nested(pack)
        except Exception as e:
            print(f"  ERROR downloading {pack}: {e}")
            print(f"  Download manually: {url}\n  Unzip into: {config.MODELS_DIR / pack}")
            ok = False; continue
        print(f"  [OK]  {pack} installed" if have(pack) else f"  [!!]  {pack}: files missing after unzip")
        ok = ok and have(pack)
    df = download_deepface_weights()
    print()
    if ok and df in (True, None):
        print("  Model setup complete." + ("" if df else "  (DeepFace not installed - only the InsightFace models are ready.)"))
    else:
        if not ok:
            print("  InsightFace model setup NOT complete - see messages above.")
        if df is False:
            print("  DeepFace weights NOT fully downloaded - the InsightFace models still work.")
        print("  Run Setup_Upasthiti.bat again once you have a stable internet connection; finished parts are skipped.")
    return 0 if (ok and df is not False) else 1


if __name__ == "__main__":
    code = main()
    input("\nPress Enter to close...")
    sys.exit(code)
