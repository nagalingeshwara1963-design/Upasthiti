import sys, queue, tkinter as tk, time
import threading
import tempfile
from tkinter import messagebox, simpledialog
import customtkinter as ctk
from .. import config, i18n, auth
from ..i18n import T, lang, LANGS
from ..db import DB
from ..services import Service
from . import theme as th

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


# Drives both the visible navigation and staff page registration order.
STAFF_NAVIGATION = (
    ("home", "home", ("admin", "faculty")),
    ("enroll", "enroll", ("admin", "faculty")),
    ("photos", "photos", ("admin", "faculty")),
    ("attendance", "attendance", ("admin", "faculty")),
    ("reports", "reports", ("admin", "faculty")),
    ("email_center", "Email Center", ("admin", "faculty")),
    ("recovery", "Recovery", ("admin", "faculty")),
    ("reviews", "Review Requests", ("admin", "faculty")),
    ("settings", "settings", ("admin",)),
    ("models", "models", ("admin",)),
    ("help", "help", ("admin", "faculty")),
)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        config.ensure_dirs()
        self.db = DB(); self.svc = Service(self.db)
        self.staged = []                      # group photos waiting for a session
        self.current = "home"
        self.title("Upasthiti - Face Recognition Attendance")
        self.minsize(980, 640)
        self.geometry("1280x760")
        try: self.state("zoomed")
        except Exception:
            try: self.attributes("-zoomed", True)
            except Exception: pass
        i18n.set_lang(self.db.get("language", "en"))
        self.class_var = tk.StringVar()
        self._q = queue.Queue()
        self._email_schedule_busy = False
        self._demo_active = False
        from ..email_service import EmailService
        self.email_service = EmailService(self.db, self.post)

        if auth.current_user():
            self.build("home")
        else:
            self.show_login()

        self.after(40, self._pump)
        self.after(1000, self._email_schedule_tick)

    def _email_schedule_tick(self):
        if auth.current_role() == "admin" and not self._email_schedule_busy:
            self._email_schedule_busy = True
            def work():
                try:
                    self.email_service.process_due_schedules()
                except Exception as exc:
                    self.post(lambda text=str(exc)[:300]: print("Email schedule processing error:", text))
                finally:
                    self.post(lambda: setattr(self, "_email_schedule_busy", False))
            threading.Thread(target=work, name="UpasthitiEmailSchedule", daemon=True).start()
        try:
            self.after(60_000, self._email_schedule_tick)
        except tk.TclError:
            pass

    def show_login(self):
        """Render the login card directly in the main window."""
        for w in self.winfo_children():
            w.destroy()
        self.configure(fg_color=th.BG)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        center_wrapper = ctk.CTkFrame(self, fg_color="transparent")
        center_wrapper.grid(row=0, column=0)

        c = th.card(center_wrapper, width=460)
        c.pack(padx=20, pady=20)

        ctk.CTkLabel(c, text="👁  " + T("app"), font=th.font(26, True, lang()), text_color=th.BLUE_DK).pack(pady=(24, 2))
        ctk.CTkLabel(c, text=T("login_title"), font=th.font(13, False, lang()), text_color=th.GREY).pack(pady=(0, 16))

        # Role dropdown
        ctk.CTkLabel(c, text=T("role"), text_color=th.GREY, font=th.font(12, True, lang()), anchor="w").pack(anchor="w", padx=40, pady=(0, 4))
        self._login_role_var = tk.StringVar(value="Admin")
        self._login_role_menu = ctk.CTkOptionMenu(c, values=["Admin", "Faculty", "Student", "Maintenance"],
                                                  variable=self._login_role_var,
                                                  width=360, height=40, fg_color=th.BLUE, button_color=th.BLUE_DK,
                                                  command=self._on_role_change)
        self._login_role_menu.pack(pady=(0, 14))

        # Fields container
        self._login_fields = ctk.CTkFrame(c, fg_color="transparent")
        self._login_fields.pack(fill="x", padx=40)

        self._login_user_var = tk.StringVar(value="admin")
        self._login_pw_var = tk.StringVar()
        self._login_student_name_var = tk.StringVar()
        self._login_student_code_var = tk.StringVar()

        self._login_user_entry = ctk.CTkEntry(self._login_fields, textvariable=self._login_user_var,
                                              placeholder_text=T("username"), width=360, height=40)

        fac_list = [u["username"] for u in auth.list_users(self.db) if u["role"] == "faculty"]
        self._login_fac_menu = ctk.CTkOptionMenu(self._login_fields, values=fac_list or ["(No faculty accounts)"],
                                                 variable=self._login_user_var, width=360, height=40,
                                                 fg_color=th.BLUE, button_color=th.BLUE_DK)

        self._login_pw_entry = ctk.CTkEntry(self._login_fields, textvariable=self._login_pw_var,
                                            placeholder_text=T("password"), show="*", width=360, height=40)
        self._login_pw_entry.bind("<Return>", lambda e: self._do_login_attempt())

        self._login_student_info = ctk.CTkFrame(self._login_fields, fg_color="transparent")
        self._login_student_name_entry = ctk.CTkEntry(self._login_student_info, textvariable=self._login_student_name_var,
            placeholder_text="Student name", width=360, height=40)
        self._login_student_name_entry.pack(pady=(0, 8))
        self._login_student_code_entry = ctk.CTkEntry(self._login_student_info, textvariable=self._login_student_code_var,
            placeholder_text="Student ID", width=360, height=40)
        self._login_student_code_entry.pack(pady=(0, 8))
        self._login_student_pw_entry = ctk.CTkEntry(self._login_student_info, textvariable=self._login_pw_var,
            placeholder_text="Password (first login: Student ID)", show="*", width=360, height=40)
        self._login_student_pw_entry.pack(pady=(0, 8))
        self._login_student_pw_entry.bind("<Return>", lambda e: self._do_login_attempt())

        self._login_err_lbl = ctk.CTkLabel(c, text="", text_color=th.RED, font=th.font(12, True))
        self._login_err_lbl.pack(pady=(4, 6))

        self._login_btn = ctk.CTkButton(c, text=T("login_btn"), height=44, width=360,
                                        fg_color=th.BLUE, hover_color=th.BLUE_DK, font=th.font(15, True, lang()),
                                        command=self._do_login_attempt)
        self._login_btn.pack(pady=(0, 24))
        self._demo_btn = ctk.CTkButton(c, text="Explore isolated Demo Mode", height=34, width=260,
            fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB", command=self.enter_demo)
        self._demo_btn.pack(pady=(0, 20))

        self._on_role_change("Admin")

        if not auth.has_any_account(self.db):
            self.after(200, self._bootstrap_admin)

    def _on_role_change(self, role):
        self._login_pw_var.set("")
        self._login_err_lbl.configure(text="")
        if role in ("Admin", "Maintenance"):
            self._login_student_info.pack_forget()
            self._login_fac_menu.pack_forget()
            self._login_user_entry.pack(pady=(0, 10))
            self._login_user_var.set("admin")
            self._login_user_entry.configure(state="disabled")
            self._login_pw_entry.pack(pady=(0, 10))
            self._login_btn.configure(text=T("login_btn"))
            self._login_pw_entry.focus_set()
        elif role == "Faculty":
            self._login_student_info.pack_forget()
            self._login_user_entry.pack_forget()
            self._login_fac_menu.pack(pady=(0, 10))
            facs = [u["username"] for u in auth.list_users(self.db) if u["role"] == "faculty"]
            if facs:
                self._login_user_var.set(facs[0])
            self._login_pw_entry.pack(pady=(0, 10))
            self._login_btn.configure(text=T("login_btn"))
            self._login_pw_entry.focus_set()
        elif role == "Student":
            self._login_user_entry.pack_forget()
            self._login_fac_menu.pack_forget()
            self._login_student_info.pack(fill="x", pady=(0, 10))
            self._login_btn.configure(text=T("login_btn"))
            self._login_student_name_entry.focus_set()

    def _bootstrap_admin(self):
        pw = simpledialog.askstring("Upasthiti", "Welcome! Set the admin password to begin:", show="*", parent=self)
        if pw and pw.strip():
            auth.set_password(self.db, "admin", "admin", pw.strip())
            self._login_user_var.set("admin")
            self._login_pw_entry.focus_set()
            messagebox.showinfo("Upasthiti", "Admin password set. You can now log in.", parent=self)
        else:
            messagebox.showwarning("Upasthiti", "Admin password is required to set up the system.", parent=self)
            self._bootstrap_admin()

    def _do_login_attempt(self):
        role_choice = self._login_role_var.get()
        if role_choice == "Student":
            if not auth.student_login(self.db, self._login_student_name_var.get(),
                                      self._login_student_code_var.get(), self._login_pw_var.get()):
                self._login_err_lbl.configure(text="Student name, ID, or password is incorrect.")
                return
            if auth.student_must_change_password():
                first = simpledialog.askstring("Create a new password", "Set a new password (10–256 characters):", show="*", parent=self)
                second = simpledialog.askstring("Confirm password", "Enter the new password again:", show="*", parent=self) if first else None
                if not first or first != second:
                    auth.logout()
                    self._login_err_lbl.configure(text="Password change is required to continue; the values did not match.")
                    return
                try: auth.change_student_password(self.db, first)
                except ValueError as exc:
                    auth.logout(); self._login_err_lbl.configure(text=str(exc)); return
            self._login_pw_var.set("")
            self.build("home")
            return

        uname = self._login_user_var.get().strip()
        pw = self._login_pw_var.get()

        if role_choice in ("Admin", "Maintenance"):
            uname = "admin"

        if not pw:
            self._login_err_lbl.configure(text=T("please_enter_password"))
            return

        role = auth.login(self.db, uname, pw)
        if role:
            self._login_pw_var.set("")
            self.build("home")
        else:
            self._login_err_lbl.configure(text=T("wrong_pw"))

    def logout(self):
        if self._demo_active:
            self.exit_demo(); return
        if messagebox.askyesno("Upasthiti", "Are you sure you want to log out?", parent=self):
            auth.logout()
            self.show_login()

    def enter_demo(self):
        """Switch to synthetic data in a temporary directory; never copy production data."""
        if auth.current_role() is not None or self._demo_active: return
        active = self.db.q("SELECT COUNT(*) AS n FROM email_deliveries WHERE status IN ('pending','sending')")[0]["n"]
        if active or not self.email_service.wait_idle(timeout=0.2):
            messagebox.showwarning("Upasthiti", "Demo Mode is unavailable while production email work is active. Wait for it to finish and try again.", parent=self); return
        from ..email_service import EmailService
        production_mail = self.email_service
        production_mail.shutdown(timeout=1)
        production_mail._thread.join(timeout=2)
        if production_mail._thread.is_alive():
            messagebox.showwarning("Upasthiti", "The production email worker did not stop cleanly; Demo Mode was not entered.", parent=self); return
        from .. import demo_mode
        self._demo_tmp = tempfile.TemporaryDirectory(prefix="upasthiti-demo-")
        self._production = {"db": self.db, "svc": self.svc, "config": demo_mode.swap_config_root(self._demo_tmp.name)}
        demo_db = None
        try:
            demo_db = DB(config.DB_PATH)
            demo_mode.seed_demo_database(demo_db)
            self.db = demo_db
            self.svc = Service(demo_db)
            self.email_service = EmailService(demo_db, self.post, disabled=True)
            self.class_var.set("DEMO · Sample Class")
            self._demo_active = True
            auth.login(self.db, "admin", "demo-admin-only")
            self.build("home")
        except Exception:
            if hasattr(self, "email_service") and self.email_service is not production_mail:
                self.email_service.shutdown(timeout=1); self.email_service._thread.join(timeout=2)
            if demo_db is not None:
                try: demo_db.con.close()
                except Exception: pass
            demo_mode.restore_config_paths(self._production["config"])
            self.db, self.svc = self._production["db"], self._production["svc"]
            self.email_service = EmailService(self.db, self.post)
            self._demo_tmp.cleanup(); self._demo_active = False
            raise

    def exit_demo(self):
        if not self._demo_active: return
        if not messagebox.askyesno("Exit Demo Mode", "Discard this temporary demo session and return to the working data?", parent=self): return
        from .. import demo_mode
        auth.logout()
        self.email_service.shutdown(timeout=1); self.email_service._thread.join(timeout=2)
        self.db.con.close()
        demo_mode.restore_config_paths(self._production["config"])
        self.db, self.svc = self._production["db"], self._production["svc"]
        from ..email_service import EmailService
        self.email_service = EmailService(self.db, self.post)
        self._demo_tmp.cleanup(); self._demo_active = False
        self._production = None
        self.class_var.set("")
        self.show_login()

    def create_backup(self):
        if auth.current_role() != "admin": raise PermissionError("Only an administrator can create backups.")
        from tkinter import filedialog
        from .. import backup
        path = filedialog.asksaveasfilename(parent=self, title="Create Upasthiti backup",
            defaultextension=".zip", initialfile="upasthiti_backup.zip", filetypes=[("Upasthiti backup", "*.zip")])
        if not path: return
        try:
            output = backup.create_backup(self.db, path)
            self.db.put("backup_last_path", str(output)); self.db.put("backup_last_at", time.time())
            messagebox.showinfo("Upasthiti", f"Verified backup created:\n{output}\n\nThis archive contains student and biometric data. Store it on a protected local drive. Protected email credentials may be restorable only under the same Windows user account.", parent=self)
        except Exception as exc: messagebox.showerror("Upasthiti", f"Backup failed; no backup was reported as complete.\n{exc}", parent=self)

    def restore_backup(self):
        if auth.current_role() != "admin": raise PermissionError("Only an administrator can restore backups.")
        from tkinter import filedialog
        from .. import backup
        path = filedialog.askopenfilename(parent=self, title="Select Upasthiti backup", filetypes=[("Upasthiti backup", "*.zip")])
        if not path: return
        try: details = backup.validate_backup(path)
        except Exception as exc:
            messagebox.showerror("Upasthiti", f"Backup validation failed; current data was not changed.\n{exc}", parent=self); return
        if not messagebox.askyesno("Restore Upasthiti backup", f"This replaces the current database, enrollment photos, galleries, and reports with a validated backup from {details['created_at']:.0f}. A verified pre-restore backup will be kept in data/backups. Continue?", parent=self): return
        active = self.db.q("SELECT COUNT(*) AS n FROM email_deliveries WHERE status IN ('pending','sending')")[0]["n"]
        if active or not self.email_service.wait_idle(timeout=0.2):
            messagebox.showwarning("Upasthiti", "Wait until active email work finishes before restoring.", parent=self); return
        self.email_service.shutdown(timeout=1); self.email_service._thread.join(timeout=3)
        if self.email_service._thread.is_alive():
            messagebox.showwarning("Upasthiti", "The email worker did not stop cleanly. Restart the application before restoring.", parent=self); return
        from ..db import DB
        try: self.db = backup.restore_backup(self.db, path)
        except Exception as exc:
            try: self.db.q("SELECT 1")
            except Exception: self.db = DB(config.DB_PATH)
            self.svc = Service(self.db)
            from ..email_service import EmailService
            self.email_service = EmailService(self.db, self.post)
            messagebox.showerror("Upasthiti", f"Restore failed and the previous data was restored from rollback.\n{exc}", parent=self)
            return
        self.svc = Service(self.db)
        from ..email_service import EmailService
        self.email_service = EmailService(self.db, self.post)
        self.db.put("backup_last_path", str(path)); self.db.put("backup_last_at", time.time())
        self.class_var.set(""); self.build("home")
        messagebox.showinfo("Upasthiti", "Backup restored. The pre-restore snapshot is saved in data/backups.", parent=self)

    @property
    def user_name(self):
        return auth.current_user() or "admin"

    @property
    def user_role(self):
        return auth.current_role() or "admin"

    # ---- thread-safe UI calls: worker threads call app.post(fn); fn runs on the UI thread ----
    def post(self, fn):
        self._q.put(fn)

    def _pump(self):
        try:
            while True:
                self._q.get_nowait()()
        except queue.Empty:
            pass
        except Exception as e:                       # never let one bad callback kill the loop
            print("UI callback error:", e)
        self.after(40, self._pump)

    # ---- helpers ----
    @property
    def class_id(self):
        n = self.class_var.get()
        r = self.db.q("SELECT id FROM classes WHERE name=?", (n,)) if n else []
        return r[0]["id"] if r else None

    def class_names(self):
        classes = self.db.classes()
        if auth.current_role() == "faculty":
            allowed = set(self.db.faculty_class_ids(auth.current_user()))
            classes = [c for c in classes if c["id"] in allowed]
        return [c["name"] for c in classes]

    def notify_changed(self):
        for p in self.pages.values():
            if hasattr(p, "refresh"): p.refresh()

    def _class_changed(self, _value=None):
        current_id = self.class_id
        previous_id = getattr(self, "_last_class_id", current_id)
        if previous_id != current_id:
            had_staged = bool(self.staged)
            self.staged.clear()
            self.smart_capture_result = None
            enroll = getattr(self, "pages", {}).get("enroll")
            if enroll is not None and getattr(enroll, "groups", None):
                enroll.groups, enroll.failed = [], []
                enroll.render()
                if hasattr(enroll, "status"):
                    enroll.status.configure(text="Class changed; unsaved enrollment photos were cleared.", text_color=th.AMBER)
            photos = getattr(self, "pages", {}).get("photos")
            if photos is not None: photos._pending_smart_result = None
            if had_staged:
                messagebox.showinfo("Upasthiti", "Changing class cleared staged attendance and unsaved enrollment photos to prevent saving them into the wrong class.", parent=self)
        self._last_class_id = current_id
        self.notify_changed()

    def new_class(self):
        if auth.current_role() != "admin": return
        name = simpledialog.askstring("Upasthiti", "Class name (e.g. ME 3rd Sem A  or  3106_2023_ME_A):", parent=self)
        if name and name.strip():
            try:
                self.db.add_class(name.strip())
            except Exception:
                messagebox.showwarning("Upasthiti", "A class with that name already exists."); return
            self.class_menu.configure(values=self.class_names()); self.class_var.set(name.strip()); self._class_changed()

    def set_language(self, label):
        code = next(k for k, v in LANGS.items() if v == label)
        self.db.put("language", code); i18n.set_lang(code); self.build(self.current)

    # ---- layout ----
    def build(self, start="home"):
        for w in self.winfo_children(): w.destroy()
        self.configure(fg_color=th.BG)
        if auth.current_role() == "student":
            self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(0, weight=1)
            holder = ctk.CTkFrame(self, fg_color=th.BG, corner_radius=0)
            holder.grid(row=0, column=0, sticky="nsew")
            from .student_portal import StudentPortalPage
            self.pages = {"portal": StudentPortalPage(holder, self)}
            self.current = "portal"
            self.pages["portal"].place(relx=0, rely=0, relwidth=1, relheight=1)
            return
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        sb = ctk.CTkFrame(self, fg_color=th.BLUE_DK, corner_radius=0, width=210); sb.grid(row=0, column=0, sticky="nsw"); sb.grid_propagate(False)
        ctk.CTkLabel(sb, text="👁  " + T("app"), text_color="white", font=th.font(24, True, lang())).pack(anchor="w", padx=20, pady=(24, 2))
        ctk.CTkLabel(sb, text=T("tagline"), text_color="#90CAF9", font=th.font(11)).pack(anchor="w", padx=22, pady=(0, 20))
        nav_area = ctk.CTkScrollableFrame(sb, fg_color="transparent", height=390)
        nav_area.pack(fill="both", expand=True, padx=2, pady=(0, 8))
        self.nav = {}
        role = auth.current_role() or "admin"
        is_student = (role == "student")
        staff_role = role if role in ("admin", "faculty") else "admin"

        # Students use their separate portal. Staff use the shared order above.
        nav_items = [("home", "home"), ("reports", "reports")] if is_student else [
            (key, label) for key, label, roles in STAFF_NAVIGATION if staff_role in roles]
        for key, text_key in nav_items:
            label = T(text_key) if text_key in {"home", "enroll", "photos", "attendance", "reports", "settings", "models", "help"} else text_key
            b = ctk.CTkButton(nav_area, text=label, anchor="w", height=38, corner_radius=8, fg_color="transparent", hover_color=th.BLUE,
                              text_color="white", font=th.font(14, False, lang()), command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=8, pady=1); self.nav[key] = b

        # Bottom section of sidebar: User info + Logout + Language
        bot_frame = ctk.CTkFrame(sb, fg_color="transparent")
        bot_frame.pack(side="bottom", fill="x", padx=16, pady=14)

        if self._demo_active:
            ctk.CTkButton(bot_frame, text="Exit Demo Mode", fg_color="#8B1E1E", hover_color="#B3261E",
                          text_color="white", command=self.exit_demo).pack(side="bottom", fill="x", pady=(0, 8))

        ctk.CTkOptionMenu(bot_frame, values=list(LANGS.values()), width=170, fg_color=th.BLUE, button_color=th.BLUE, command=self.set_language,
                          font=th.font(12, False, lang())).pack(side="bottom", pady=(4, 0))
        ctk.CTkLabel(bot_frame, text=T("language"), text_color="#90CAF9", font=th.font(11, False, lang())).pack(side="bottom", anchor="w", padx=4)

        u_role = auth.current_role() or "admin"
        u_name = auth.current_user() or "admin"
        user_badge = ctk.CTkFrame(bot_frame, fg_color="#10386E", corner_radius=8)
        user_badge.pack(side="bottom", fill="x", pady=(0, 10))
        role_display = "Student (View Only)" if u_role == "student" else f"{u_name} ({u_role})"
        ctk.CTkLabel(user_badge, text=f"👤 {role_display}", text_color="white", font=th.font(11, True)).pack(anchor="w", padx=8, pady=(4, 2))
        ctk.CTkButton(user_badge, text=T("logout_btn"), height=24, fg_color="transparent", hover_color=th.BLUE,
                      text_color="#FF8A80", font=th.font(11, True, lang()), command=self.logout).pack(anchor="e", padx=6, pady=(0, 4))

        main = ctk.CTkFrame(self, fg_color=th.BG, corner_radius=0); main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(1, weight=1); main.grid_columnconfigure(0, weight=1)
        bar = ctk.CTkFrame(main, fg_color=th.WHITE, corner_radius=0, height=56); bar.grid(row=0, column=0, sticky="ew")
        self.title_lbl = ctk.CTkLabel(bar, text="", font=th.font(18, True, lang()), text_color=th.TEXT); self.title_lbl.pack(side="left", padx=20, pady=12)
        if role == "admin":
            ctk.CTkButton(bar, text=T("new_class"), width=110, height=32, fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB",
                          command=self.new_class).pack(side="right", padx=(6, 16))
        if role in ("admin", "faculty"):
            names = self.class_names()
            self.class_menu = ctk.CTkOptionMenu(bar, values=names or ["(No assigned classes)"], variable=self.class_var, width=240, height=32,
                                                fg_color=th.BLUE, button_color=th.BLUE_DK, command=self._class_changed)
            self.class_menu.pack(side="right"); ctk.CTkLabel(bar, text=T("class"), text_color=th.GREY).pack(side="right", padx=8)
            if names and self.class_var.get() not in names: self.class_var.set(names[0])
        names = self.class_names()
        if names and not self.class_var.get(): self.class_var.set(names[0])
        self._last_class_id = self.class_id
        holder = ctk.CTkFrame(main, fg_color=th.BG, corner_radius=0); holder.grid(row=1, column=0, sticky="nsew")
        from .page_enroll import EnrollPage
        from .page_misc import HomePage, ModelsPage, SettingsPage, HelpPage, PlaceholderPage
        from .email_center import EmailCenterPage
        from .staff_tools import StaffToolsPage
        def make_page(key):
            if key == "home": return HomePage(holder, self)
            if key == "enroll": return EnrollPage(holder, self)
            if key == "photos":
                from .page_photos import PhotosPage
                return PhotosPage(holder, self)
            if key == "attendance":
                from .page_attendance import AttendancePage
                return AttendancePage(holder, self)
            if key == "reports":
                from .page_reports import ReportsPage
                return ReportsPage(holder, self)
            if key == "email_center": return EmailCenterPage(holder, self)
            if key == "recovery": return StaffToolsPage(holder, self, "recovery")
            if key == "reviews":
                from .review_queue import ReviewQueuePage
                return ReviewQueuePage(holder, self)
            if key == "settings": return SettingsPage(holder, self)
            if key == "models": return ModelsPage(holder, self)
            if key == "help": return HelpPage(holder, self)
            raise KeyError(key)

        self.pages = {}
        for key, _label, roles in STAFF_NAVIGATION:
            if staff_role not in roles:
                continue
            try:
                self.pages[key] = make_page(key)
            except ImportError:
                if key in {"photos", "attendance", "reports"}:
                    self.pages[key] = PlaceholderPage(holder, self, key)
                else:
                    raise
        self.show(start)

    def show(self, key):
        role = auth.current_role()
        if role == "student":
            portal_keys = {"portal", "home", "attendance", "recovery", "reports", "reviews", "notifications", "profile", "chat"}
            if key in portal_keys and "portal" in self.pages:
                self.pages["portal"].show("home" if key == "portal" else key)
            return
        if role == "faculty":
            allowed = {key for key, _label, roles in STAFF_NAVIGATION if role in roles}
            if key not in allowed: key = "home"
        self.current = key
        for k, p in self.pages.items(): p.place_forget()
        self.pages[key].place(relx=0, rely=0, relwidth=1, relheight=1)
        for k, b in self.nav.items(): b.configure(fg_color=th.BLUE if k == key else "transparent")
        self.title_lbl.configure(text="Email Center" if key == "email_center" else T(key))
        if hasattr(self.pages[key], "refresh"): self.pages[key].refresh()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
