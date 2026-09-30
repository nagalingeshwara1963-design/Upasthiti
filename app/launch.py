"""Safe launcher: if Upasthiti fails to start, the reason is shown in a message box
and saved to data\\logs\\error.log instead of the window just closing."""
import sys, traceback, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def report(tb, show_dialog=True):
    """Write traceback to error.log and optionally show a messagebox."""
    log = ROOT / "data" / "logs"
    try:
        log.mkdir(parents=True, exist_ok=True)
        with open(log / "error.log", "a", encoding="utf-8") as f:
            f.write(f"\n=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ===\n{tb}\n")
    except Exception as write_err:
        print("Could not write error log:", write_err)

    if show_dialog:
        try:
            import tkinter
            from tkinter import messagebox
            r = tkinter.Tk(); r.withdraw()
            messagebox.showerror(
                "Upasthiti – startup error",
                "The application crashed. Details:\n\n" + tb[-1800:] +
                "\n\nFull trace saved to:\n  data\\logs\\error.log"
            )
            r.destroy()
        except Exception:
            pass  # silently ignore if Tk itself is broken


def run():
    try:
        from app.ui.main import main
        main()
    except SystemExit as e:
        if e.code not in (0, None):
            report(f"SystemExit: {e.code}", show_dialog=True)
            sys.exit(e.code)
    except Exception:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        report(tb, show_dialog=True)
        sys.exit(1)


if __name__ == "__main__":
    run()
