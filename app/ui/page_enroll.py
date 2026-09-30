import re, threading
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from . import theme as th
from ..i18n import T, lang
from .. import auth

STATUS_TXT = {"ok": ("OK", th.GREEN), "check_quality": ("Check quality", th.AMBER), "multiple_faces": ("2+ faces", th.AMBER)}


def guess_code(paths):
    """If every photo in a group is named like ID_1.jpg / ID-2.png, pre-fill ID.
    Only strips a trailing photo-number when it has its own separator (_1, -2, " 3"),
    so IDs that themselves end in a digit (e.g. UOM26JRA001) are never mangled.
    A single photo with no separator suffix keeps its full filename as the guess."""
    stems = set()
    for p in paths:
        base = re.sub(r"\.[^.]+$", "", str(p).replace("\\", "/").split("/")[-1])
        s = re.sub(r"[_\- ]\d{1,2}$", "", base)
        stems.add(s)
    return stems.pop() if len(stems) == 1 else ""


class EnrollPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=th.BG)
        self.app = app
        self.groups = []      # {"photos":[rec], "code": StringVar, "name": StringVar}
        self.failed = []
        self.tab_var = ctk.StringVar(value="Import New")
        self.tabs = ctk.CTkSegmentedButton(self, values=["Import New", "Manage Enrolled"], variable=self.tab_var, command=self.switch_tab)
        self.tabs.pack(fill="x", padx=16, pady=(12, 0))

        # --- Import New Container ---
        self.import_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.import_frame.pack(fill="both", expand=True)

        top = th.card(self.import_frame); top.pack(fill="x", padx=16, pady=(12, 6))
        actions = ctk.CTkFrame(top, fg_color="transparent"); actions.pack(fill="x", padx=8, pady=(8, 2))
        actions_first = ctk.CTkFrame(actions, fg_color="transparent"); actions_first.pack(fill="x")
        actions_second = ctk.CTkFrame(actions, fg_color="transparent"); actions_second.pack(fill="x")
        ctk.CTkButton(actions_first, text="📥  " + T("import_photos"), height=40, fg_color=th.BLUE, font=th.font(13, True, lang()),
                      command=self.pick_files).pack(side="left", padx=6, pady=6, expand=True, fill="x")
        ctk.CTkButton(actions_first, text="📱  Upload from Phone", height=40, fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB",
                      command=self.upload_from_phone).pack(side="left", padx=4, pady=6, expand=True, fill="x")
        ctk.CTkButton(actions_first, text=T("import_folder_btn"), height=40, fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB",
                      command=self.pick_folder).pack(side="left", padx=4, pady=6, expand=True, fill="x")
        ctk.CTkButton(actions_second, text=T("add_student_btn"), height=40, fg_color=th.GREEN, hover_color="#1B5E20", text_color="white",
                      font=th.font(13, True, lang()), command=self.add_student_card).pack(side="left", padx=6, pady=6, expand=True, fill="x")
        ctk.CTkButton(actions_second, text=T("import_csv_btn"), height=40, fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB",
                      font=th.font(13, True, lang()), command=self.import_csv_ids).pack(side="left", padx=6, pady=6, expand=True, fill="x")
        status_row = ctk.CTkFrame(top, fg_color="transparent"); status_row.pack(fill="x", padx=16, pady=(0, 10))
        self.status = ctk.CTkLabel(status_row, text=T("enroll_hint"),
                                   text_color=th.GREY, font=th.font(12, False, lang()), wraplength=760, justify="left", anchor="w")
        self.status.pack(fill="x")
        self.bar = ctk.CTkProgressBar(self.import_frame, height=8, progress_color=th.BLUE); self.bar.set(0)
        self.bar.pack(fill="x", padx=18, pady=(0, 4))
        self.body = ctk.CTkScrollableFrame(self.import_frame, fg_color=th.BG)
        self.body.pack(fill="both", expand=True, padx=10, pady=2)
        bottom = th.card(self.import_frame); bottom.pack(fill="x", padx=16, pady=(6, 12))
        self.count = ctk.CTkLabel(bottom, text="", text_color=th.GREY); self.count.pack(side="left", padx=14, pady=10)
        self.save_btn = ctk.CTkButton(bottom, text="💾  " + T("save_students"), height=40, fg_color=th.GREEN, hover_color="#1B5E20",
                                      font=th.font(13, True, lang()), command=self.save, state="disabled")
        self.save_btn.pack(side="right", padx=12, pady=10)
        self.enrolled_lbl = ctk.CTkLabel(bottom, text="", text_color=th.GREY); self.enrolled_lbl.pack(side="right", padx=8)

        # --- Manage Enrolled Container ---
        self.manage_frame = ctk.CTkScrollableFrame(self, fg_color=th.BG)

        self.switch_tab("Import New")
        self.render()

    def switch_tab(self, name):
        if name == "Import New":
            self.manage_frame.pack_forget()
            self.import_frame.pack(fill="both", expand=True)
            self.render()
        else:
            self.import_frame.pack_forget()
            self.manage_frame.pack(fill="both", expand=True, padx=10, pady=10)
            self.render_manage()

    def refresh(self):
        cid = self.app.class_id
        n = len(self.app.db.students(cid)) if cid else 0
        self.enrolled_lbl.configure(text=f"Enrolled in this class: {n}")
        if self.tab_var.get() == "Manage Enrolled":
            self.render_manage()

    # ---------- manual add student ----------
    def add_student_card(self):
        new_g = {"photos": [], "code": tk.StringVar(), "name": tk.StringVar(), "recipients": []}
        self.groups.append(new_g)
        self.render()
        self.status.configure(text=f"Added Student {len(self.groups)} card. Click '➕ Add Photo' to attach photos.", text_color=th.BLUE)

    def add_photo_to_group(self, group_idx):
        paths = filedialog.askopenfilenames(
            title=f"Select photo(s) for Student {group_idx + 1}",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp"), ("All", "*.*")]
        )
        if not paths: return
        self.status.configure(text=f"Reading {len(paths)} photo(s)...", text_color=th.BLUE)
        self.update_idletasks()
        hub = self.app.svc.get_hub()
        from ..services import imread, enroll_photo
        added = 0
        for p in paths:
            img = imread(p)
            if img is not None:
                embs, info = enroll_photo(hub, img)
                if embs is not None:
                    self.groups[group_idx]["photos"].append({
                        "path": p, "embs": embs, "info": info, "image": img
                    })
                    added += 1
                else:
                    messagebox.showwarning("Upasthiti", f"No readable face detected in:\n{p}")
            else:
                messagebox.showwarning("Upasthiti", f"Cannot open image file:\n{p}")
        if added > 0:
            self.status.configure(text=f"Added {added} photo(s) to Student {group_idx + 1}.", text_color=th.GREEN)
            self.render()

    def remove_group(self, group_idx):
        if group_idx < len(self.groups):
            del self.groups[group_idx]
            self.render()

    def add_enrollment_email(self, group_idx):
        self.groups[group_idx].setdefault("recipients", []).append({"email": tk.StringVar(), "label": tk.StringVar(value="Student")})
        self.render()

    def remove_enrollment_email(self, group_idx, recipient_idx):
        del self.groups[group_idx]["recipients"][recipient_idx]
        self.render()

    # ---------- import ----------
    def pick_files(self):
        paths = filedialog.askopenfilenames(title="Select enrollment photos", filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp"), ("All", "*.*")])
        if paths: self.start_import(list(paths), append=True)

    def upload_from_phone(self):
        from .phone_upload import PhoneUploadDialog
        PhoneUploadDialog(self, self._phone_upload_received)

    def _phone_upload_received(self, paths, cleanup):
        if not paths:
            cleanup()
            messagebox.showinfo("Upasthiti", "No photos were uploaded.")
            return
        self.start_import(paths, append=True, cleanup=cleanup)

    def pick_folder(self):
        import os
        d = filedialog.askdirectory(title="Select folder of enrollment photos")
        if d:
            paths = sorted(os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")))
            if paths: self.start_import(paths, append=True)

    def start_import(self, paths, append=True, cleanup=None):
        if not self.app.class_id:
            if cleanup: cleanup()
            messagebox.showinfo("Upasthiti", "Create or select a class first."); return
        self.status.configure(text=f"Reading {len(paths)} photos... (first run loads face models)", text_color=th.BLUE)
        self.save_btn.configure(state="disabled"); self.bar.set(0)
        def work():
            try:
                recs, groups, failed = self.app.svc.import_photos(paths, lambda p: self.app.post(lambda: self.bar.set(p)))
                self.app.post(lambda: self.show_result(groups, failed, append=append))
            except Exception as e:
                self.app.post(lambda: (self.status.configure(text=f"Error: {e}", text_color=th.RED), messagebox.showerror("Upasthiti", str(e))))
            finally:
                if cleanup:
                    cleanup()
        threading.Thread(target=work, daemon=True).start()

    def show_result(self, groups, failed, append=True):
        self.failed = failed
        new_groups = [{"photos": g, "code": tk.StringVar(value=guess_code([r["path"] for r in g])),
                       "name": tk.StringVar(), "recipients": []} for g in groups]
        if append and self.groups:
            self.groups.extend(new_groups)
        else:
            self.groups = new_groups
        total_p = sum(len(g["photos"]) for g in self.groups)
        self.status.configure(text=f"{total_p} photos across {len(self.groups)} student(s)"
                                   + (f"; {len(failed)} photo(s) had no readable face." if failed else "."), text_color=th.GREEN)
        self.bar.set(1)
        self.render()

    # ---------- preview cards ----------
    def render(self):
        for w in self.body.winfo_children(): w.destroy()
        if not self.groups and not self.failed:
            empty = ctk.CTkFrame(self.body, fg_color="transparent")
            empty.pack(pady=60)
            ctk.CTkLabel(empty, text=T("no_students_queued"),
                         text_color=th.TEXT, font=th.font(16, True, lang())).pack(pady=(0, 6))
            ctk.CTkLabel(empty, text=T("no_students_detail"),
                         text_color=th.GREY, font=th.font(13, False, lang()), justify="center").pack(pady=(0, 16))
            ctk.CTkButton(empty, text=T("add_student_now"), height=38, fg_color=th.GREEN, hover_color="#1B5E20",
                          font=th.font(13, True, lang()), command=self.add_student_card).pack()

        if self.failed:
            f = th.card(self.body); f.pack(fill="x", padx=6, pady=6)
            ctk.CTkLabel(f, text=f"⚠  {len(self.failed)} photo(s) with no face found - retake these", text_color=th.RED, font=th.font(13, True)).pack(anchor="w", padx=12, pady=(10, 4))
            row = ctk.CTkFrame(f, fg_color="transparent"); row.pack(anchor="w", padx=10, pady=(0, 10))
            for x in self.failed[:12]:
                if x.get("image") is not None:
                    im = th.to_ctk(x["image"], 90, 90); ctk.CTkLabel(row, image=im, text="").pack(side="left", padx=4)

        names = ["Move to..."] + [f"Student {i+1}" for i in range(len(self.groups))] + ["New student", "Remove"]
        for gi, g in enumerate(self.groups):
            c = th.card(self.body); c.pack(fill="x", padx=6, pady=6)
            head = ctk.CTkFrame(c, fg_color="transparent"); head.pack(fill="x", padx=12, pady=(10, 6))
            ctk.CTkLabel(head, text=f"Student {gi+1}", font=th.font(15, True), text_color=th.BLUE).pack(side="left")
            ctk.CTkLabel(head, text=T("student_id"), text_color=th.GREY).pack(side="left", padx=(16, 4))
            ctk.CTkEntry(head, textvariable=g["code"], width=150, placeholder_text=T("id_placeholder")).pack(side="left")
            ctk.CTkLabel(head, text=T("name"), text_color=th.GREY).pack(side="left", padx=(14, 4))
            ctk.CTkEntry(head, textvariable=g["name"], width=200, placeholder_text=T("full_name_field")).pack(side="left")

            # Actions on right side of card header
            ctk.CTkButton(head, text=T("remove_btn2"), width=75, height=28, fg_color="#FFCDD2", text_color=th.RED, hover_color="#EF9A9A",
                          font=th.font(11, True), command=lambda idx=gi: self.remove_group(idx)).pack(side="right", padx=(4, 0))
            ctk.CTkButton(head, text=T("add_photo_btn2"), width=95, height=28, fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB",
                          font=th.font(11, True), command=lambda idx=gi: self.add_photo_to_group(idx)).pack(side="right", padx=(4, 4))

            n = len(g["photos"])
            if n == 0:
                ctk.CTkLabel(head, text=T("no_photos_badge"), text_color=th.RED, font=th.font(11, True)).pack(side="right", padx=8)
            elif n < 4:
                ctk.CTkLabel(head, text=f"⚠ {n} photo(s) - 4 recommended", text_color=th.AMBER, font=th.font(11, True)).pack(side="right", padx=8)
            else:
                ctk.CTkLabel(head, text=f"✔ {n} photos", text_color=th.GREEN, font=th.font(11, True)).pack(side="right", padx=8)

            row = ctk.CTkFrame(c, fg_color="transparent"); row.pack(fill="x", padx=10, pady=(0, 10))
            if not g["photos"]:
                no_ph = ctk.CTkFrame(row, fg_color="#F5F7FA", corner_radius=8)
                no_ph.pack(fill="x", padx=4, pady=4)
                ctk.CTkLabel(no_ph, text=T("no_photos_for_student"), text_color=th.GREY, font=th.font(12)).pack(side="left", padx=14, pady=10)
                ctk.CTkButton(no_ph, text=T("select_photos_btn2"), width=120, height=28, fg_color=th.BLUE, hover_color=th.BLUE_DK,
                              command=lambda idx=gi: self.add_photo_to_group(idx)).pack(side="right", padx=14, pady=10)
            else:
                for pi, r in enumerate(g["photos"]):
                    cell = ctk.CTkFrame(row, fg_color="transparent"); cell.pack(side="left", padx=6)
                    b = r["info"].get("bbox")
                    col = (60, 160, 40) if r["info"]["status"] == "ok" else (0, 140, 240)
                    r.setdefault("_thumb", th.to_ctk(r["image"], 130, 130, box=b, color=col))
                    ctk.CTkLabel(cell, image=r["_thumb"], text="").pack()
                    txt, tc = STATUS_TXT.get(r["info"]["status"], ("?", th.GREY))
                    ctk.CTkLabel(cell, text=txt, text_color=tc, font=th.font(11, True)).pack()
                    ctk.CTkOptionMenu(cell, values=names, width=110, height=24, fg_color=th.BLUE_LT, text_color=th.BLUE, button_color=th.BLUE_LT,
                                      command=lambda v, gi=gi, pi=pi: self.move(gi, pi, v)).pack(pady=2)

            email_box = ctk.CTkFrame(c, fg_color="transparent"); email_box.pack(fill="x", padx=12, pady=(0, 10))
            ctk.CTkLabel(email_box, text="Email Recipients (optional)", text_color=th.GREY,
                         font=th.font(11, True)).pack(side="left", padx=(0, 8))
            for ri, recipient in enumerate(g.setdefault("recipients", [])):
                ctk.CTkEntry(email_box, textvariable=recipient["email"], width=205,
                             placeholder_text="student@example.edu").pack(side="left", padx=3)
                ctk.CTkEntry(email_box, textvariable=recipient["label"], width=90,
                             placeholder_text="Student / Parent").pack(side="left", padx=3)
                ctk.CTkButton(email_box, text="×", width=25, fg_color=th.RED,
                              command=lambda gi=gi, ri=ri: self.remove_enrollment_email(gi, ri)).pack(side="left", padx=2)
            ctk.CTkButton(email_box, text="+ Add Email", width=95, fg_color=th.BLUE_LT, text_color=th.BLUE,
                          command=lambda gi=gi: self.add_enrollment_email(gi)).pack(side="left", padx=4)

        self.update_count()

    def move(self, gi, pi, target):
        if target == "Move to...": return
        rec = self.groups[gi]["photos"].pop(pi)
        if target == "Remove": pass
        elif target == "New student":
            self.groups.append({"photos": [rec], "code": tk.StringVar(), "name": tk.StringVar(), "recipients": []})
        else:
            ti = int(target.split()[-1]) - 1
            if ti < len(self.groups):
                self.groups[ti]["photos"].append(rec)
        self.groups = [g for g in self.groups if g["photos"] or g["code"].get() or g["name"].get()]
        self.render()

    def update_count(self):
        valid = [g for g in self.groups if g["photos"]]
        self.count.configure(text=f"{len(valid)} student(s) with photos to save" if valid else "")
        self.save_btn.configure(state="normal" if valid else "disabled")
        self.refresh()

    # ---------- save ----------
    def save(self):
        cid = self.app.class_id
        valid = [g for g in self.groups if g["photos"]]
        if not valid:
            messagebox.showwarning("Upasthiti", "Attach at least one photo before saving."); return
        codes = [g["code"].get().strip().upper() for g in valid]
        if any(not c for c in codes):
            messagebox.showwarning("Upasthiti", "Every student needs an ID."); return
        dup = {c for c in codes if codes.count(c) > 1}
        if dup:
            messagebox.showwarning("Upasthiti", f"Duplicate ID(s): {', '.join(sorted(dup))}"); return
        existing = {s["code"] for s in self.app.db.students(cid)}
        both = [c for c in codes if c in existing]
        if both and not messagebox.askyesno("Upasthiti", f"{len(both)} ID(s) already exist in this class ({', '.join(both[:5])}...). Add these photos to them?"):
            return
        from ..email_service import normalize_email
        students = []
        try:
            for c, g in zip(codes, valid):
                recipients = []
                for row in g.get("recipients", []):
                    address = row["email"].get().strip()
                    if address:
                        recipients.append({"email": normalize_email(address), "label": row["label"].get().strip()})
                if len({r["email"].casefold() for r in recipients}) != len(recipients):
                    raise ValueError(f"Duplicate email address for student {c}.")
                old = [s for s in self.app.db.students(cid) if s["code"] == c]
                if old:
                    already = {r["email"].casefold() for r in self.app.db.email_recipients(old[0]["id"])}
                    if any(r["email"].casefold() in already for r in recipients):
                        raise ValueError(f"An email address is already configured for student {c}; use Manage Enrolled to edit it.")
                students.append({"code": c, "name": g["name"].get().strip(), "photos": g["photos"],
                                 "email_recipients": recipients})
        except ValueError as exc:
            messagebox.showwarning("Upasthiti", str(exc), parent=self); return
        self.status.configure(text=T("saving_status"), text_color=th.BLUE); self.update_idletasks()
        try:
            self.app.svc.save_enrollment(cid, students)
        except Exception as exc:
            self.status.configure(text="Enrollment was not saved.", text_color=th.RED)
            messagebox.showerror("Upasthiti", str(exc), parent=self)
            return
        self.groups, self.failed = [], []
        self.render()
        self.status.configure(text=f"Saved {len(students)} students.", text_color=th.GREEN)
        self.app.notify_changed()
        self._warn_similar(cid, codes)

    def _warn_similar(self, cid, new_codes):
        """After saving, check whether any of the just-added students look unusually
        close to another enrolled student (possible duplicate enrollment, or true
        lookalikes/twins who will need extra distinguishing photos)."""
        try:
            names = {s["code"]: (s["name"] or s["code"]) for s in self.app.db.students(cid)}
            seen, lines = set(), []
            for code in new_codes:
                for c1, c2, dist in self.app.svc.find_similar_students(cid, exclude_code=code):
                    key = tuple(sorted((c1, c2)))
                    if key in seen: continue
                    seen.add(key)
                    lines.append(f"  \u2022 {names.get(c1, c1)} ({c1})  and  {names.get(c2, c2)} ({c2})  -  very close match")
            if lines:
                messagebox.showwarning("Upasthiti - similar faces detected",
                    "These enrolled students look unusually similar to the system:\n\n" + "\n".join(lines) +
                    "\n\nThis can mean the same person was enrolled twice under two IDs, or the students are "
                    "genuine lookalikes (e.g. twins). If they are different people, add 1-2 more distinguishing "
                    "photos for each in Manage Enrolled so attendance can tell them apart reliably.")
        except Exception as e:
            print("similar-face check skipped:", e)

    # ---------- manage enrolled ----------
    def render_manage(self):
        for w in self.manage_frame.winfo_children(): w.destroy()
        cid = self.app.class_id
        if not cid:
            ctk.CTkLabel(self.manage_frame, text=T("enroll_select_class_first"), text_color=th.GREY, font=th.font(14)).pack(pady=60)
            return
        ctk.CTkButton(self.manage_frame, text="Rebuild Recognition Gallery", height=32,
                      fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB",
                      command=self.rebuild_gallery).pack(anchor="w", padx=8, pady=(4, 8))
        students = self.app.db.students(cid)
        if not students:
            ctk.CTkLabel(self.manage_frame, text=T("no_students_class"), text_color=th.GREY, font=th.font(14)).pack(pady=60)
            return
        
        for st in students:
            c = th.card(self.manage_frame); c.pack(fill="x", padx=6, pady=6)
            head = ctk.CTkFrame(c, fg_color="transparent"); head.pack(fill="x", padx=12, pady=(10, 4))
            ctk.CTkLabel(head, text=f"{st['name'] or st['code']} ({st['code']})", font=th.font(14, True), text_color=th.TEXT).pack(side="left")
            
            ctk.CTkButton(head, text=T("delete_student_btn"), width=110, height=26, fg_color=th.RED, hover_color="#C62828", font=th.font(12, True),
                          command=lambda s=st: self.delete_student(s)).pack(side="right", padx=4)
            ctk.CTkButton(head, text=T("add_photos_btn2"), width=100, height=26, fg_color=th.BLUE, hover_color=th.BLUE_DK, font=th.font(12, True),
                          command=lambda s=st: self.add_photos_for_student(s)).pack(side="right", padx=4)
            ctk.CTkButton(head, text=T("history_btn"), width=90, height=26, fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB", font=th.font(12, True),
                          command=lambda s=st: StudentHistoryDialog(self, s)).pack(side="right", padx=4)
            if auth.current_role() == "admin":
                ctk.CTkButton(head, text="Emails", width=72, height=26, fg_color=th.BLUE_LT, text_color=th.BLUE,
                              hover_color="#BBDEFB", font=th.font(12, True),
                              command=lambda s=st: self.manage_emails(s)).pack(side="right", padx=4)
            
            photos = self.app.db.student_photos(cid, st['code'])
            row = ctk.CTkFrame(c, fg_color="transparent"); row.pack(anchor="w", padx=10, pady=(0, 10))
            if not photos:
                ctk.CTkLabel(row, text=T("no_photos_label2"), text_color=th.GREY).pack(side="left", padx=10)
            for p in photos:
                try:
                    import cv2
                    img = cv2.imread(p)
                    if img is None: continue
                    im = th.to_ctk(img, 100, 100)
                    cell = ctk.CTkFrame(row, fg_color="transparent"); cell.pack(side="left", padx=6)
                    l = ctk.CTkLabel(cell, image=im, text=""); l._img = im; l.pack()
                    ctk.CTkButton(cell, text=T("delete_btn"), width=60, height=22, fg_color=th.RED, hover_color="#C62828",
                                  command=lambda s=st, pth=p: self.delete_photo(s, pth)).pack(pady=2)
                except Exception:
                    pass

    def manage_emails(self, student):
        if auth.current_role() != "admin":
            messagebox.showwarning("Upasthiti", "Only an administrator can manage student email recipients.", parent=self)
            return
        from .email_recipients import StudentEmailDialog
        StudentEmailDialog(self, student)

    def add_photos_for_student(self, st):
        cid = self.app.class_id
        if not self._student_in_selected_class(cid, st):
            messagebox.showwarning("Upasthiti", "This student is not in the selected class.", parent=self); return
        paths = filedialog.askopenfilenames(title=f"Add photos for {st['name']} ({st['code']})",
                                            filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp"), ("All", "*.*")])
        if not paths: return
        recs, _, _ = self.app.svc.import_photos(list(paths))
        if not recs:
            messagebox.showerror("Upasthiti", "No valid faces found in selected photos.")
            return
        self.app.svc.save_enrollment(cid, [{"code": st['code'], "name": st['name'], "photos": recs}])
        messagebox.showinfo("Upasthiti", f"Added {len(recs)} photo(s) to {st['name']}.")
        self.render_manage()
        self.app.notify_changed()

    def delete_photo(self, st, path):
        cid = self.app.class_id
        if not self._student_in_selected_class(cid, st) or str(path) not in self.app.db.student_photos(cid, st["code"]):
            messagebox.showwarning("Upasthiti", "This photo is not part of the selected student's enrollment.", parent=self); return
        if not messagebox.askyesno("Upasthiti", f"Delete this photo from {st['name']}?"): return
        import os
        try: os.remove(path)
        except Exception: pass
        self.app.db.delete_enroll_photo(cid, st['code'], path)
        self.app.svc.rebuild_student_gallery(cid, st['code'])
        self.render_manage()
        self.app.notify_changed()

    def delete_student(self, st):
        cid = self.app.class_id
        if not self._student_in_selected_class(cid, st):
            messagebox.showwarning("Upasthiti", "This student is not in the selected class.", parent=self); return
        if not messagebox.askyesno("Upasthiti",
                f"Archive {st['name']} ({st['code']})? They will leave active enrollment and lose portal/email access. "
                "Their attendance and review history will be kept. Saved enrollment photos remain on this computer."):
            return
        self.app.svc.remove_student(cid, st['code'])
        self.render_manage()
        self.app.notify_changed()

    def rebuild_gallery(self):
        cid = self.app.class_id
        if not cid: return
        if not messagebox.askyesno("Upasthiti", 
                "Rebuild this class's recognition gallery from every active student's saved enrollment photos? "
                "Attendance history is not changed. If any active student has no usable saved photo, the existing gallery is kept.",
                parent=self):
            return
        try:
            gallery = self.app.svc.rebuild_class_gallery(cid)
        except Exception as exc:
            messagebox.showerror("Upasthiti", str(exc), parent=self)
            return
        messagebox.showinfo("Upasthiti", f"Recognition gallery rebuilt for {len(gallery.codes)} active students.", parent=self)

    def _student_in_selected_class(self, class_id, student):
        if not class_id or not auth.can_access_class(self.app.db, class_id): return False
        return bool(self.app.db.q("SELECT 1 FROM students WHERE class_id=? AND code=? AND active=1",
                                  (class_id, student.get("code"))))


    def import_csv_ids(self):
        """CSV with 2 columns: Student ID, Name (no header needed, but a header row is
        detected and skipped). Fills the guessed ID/Name of each imported photo group,
        in order - group 1 gets row 1, group 2 gets row 2, etc. Never adds or removes
        photo groups; just saves you retyping IDs you already have in a spreadsheet."""
        import csv as csv_mod
        if not self.groups:
            messagebox.showinfo("Upasthiti", "Import photos first, then use this to fill in their IDs."); return
        path = filedialog.askopenfilename(title="Select ID list (CSV: Student ID, Name)",
                                          filetypes=[("CSV file", "*.csv"), ("All files", "*.*")])
        if not path: return
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                rows = [r for r in csv_mod.reader(f) if r and r[0].strip()]
        except Exception as e:
            messagebox.showerror("Upasthiti", f"Could not read that file:\n{e}"); return
        if rows and rows[0][0].strip().lower() in ("id", "student id", "studentid", "code"):
            rows = rows[1:]  # skip a header row
        if not rows:
            messagebox.showwarning("Upasthiti", "That file has no ID rows."); return
        n = min(len(rows), len(self.groups))
        for i in range(n):
            row = rows[i]
            code = row[0].strip()
            name = row[1].strip() if len(row) > 1 else ""
            if code: self.groups[i]["code"].set(code.upper())
            if name: self.groups[i]["name"].set(name)
        msg = f"Filled {n} of {len(self.groups)} student card(s) from the CSV."
        if len(rows) != len(self.groups):
            msg += f"\n\nNote: the CSV had {len(rows)} row(s) but there are {len(self.groups)} photo group(s) - " \
                   "they were matched in order, so check the assignment is correct before saving."
        messagebox.showinfo("Upasthiti", msg)
        self.render()


class StudentHistoryDialog(ctk.CTkToplevel):
    """One student's full attendance history: every session, status and confidence."""
    def __init__(self, page, student_row):
        super().__init__(page)
        self.page, self.student = page, student_row
        self.title(f"History - {student_row['name'] or student_row['code']}")
        self.geometry("640x560"); self.configure(fg_color=th.BG)
        self.transient(page.winfo_toplevel())
        self._build()
        self.after(150, self.focus_force)

    def _build(self):
        app = self.page.app; cid = app.class_id
        rows = app.db.student_history(cid, self.student["code"])
        from .. import stats
        head = ctk.CTkFrame(self, fg_color=th.WHITE, corner_radius=0); head.pack(fill="x")
        ctk.CTkLabel(head, text=f"{self.student['name'] or self.student['code']}   ({self.student['code']})",
                    font=th.font(15, True), text_color=th.TEXT).pack(side="left", padx=16, pady=12)
        n_present = sum(1 for r in rows if r["status"] in ("P", "L"))
        n_counted = sum(1 for r in rows if r["status"] not in ("E", "OD"))
        pct = 100.0 * n_present / n_counted if n_counted else None
        pct_txt = "-" if pct is None else f"{pct:.1f}%"
        ctk.CTkLabel(head, text=pct_txt, font=th.font(16, True),
                    text_color=th.GREEN if (pct or 0) >= 75 else th.RED).pack(side="right", padx=16)
        ctk.CTkLabel(head, text=T("overall_attendance"), text_color=th.GREY).pack(side="right")
        body = ctk.CTkScrollableFrame(self, fg_color=th.BG); body.pack(fill="both", expand=True, padx=10, pady=8)
        if not rows:
            ctk.CTkLabel(body, text=T("no_history_yet"), text_color=th.GREY).pack(pady=30)
        COL = {"P": th.GREEN, "L": th.AMBER, "A": th.RED, "E": th.GREY, "OD": th.GREY}
        for r in rows:
            c = th.card(body); c.pack(fill="x", pady=3)
            line = ctk.CTkFrame(c, fg_color="transparent"); line.pack(fill="x", padx=12, pady=8)
            ctk.CTkLabel(line, text=f"{r['date']}  {r['time']}", font=th.font(12, True), text_color=th.TEXT, width=140, anchor="w").pack(side="left")
            ctk.CTkLabel(line, text=f"{r['subject'] or '-'}  {r['period'] or ''}", text_color=th.GREY, width=140, anchor="w").pack(side="left")
            if r["status"] == "P" and r["confidence"]:
                ctk.CTkLabel(line, text=f"{r['confidence']:.0f}%", text_color=th.GREY, width=50).pack(side="left")
            ctk.CTkLabel(line, text=stats.LABEL.get(r["status"], r["status"]), text_color=COL.get(r["status"], th.TEXT),
                        font=th.font(12, True)).pack(side="right")
            if r["edited"]: ctk.CTkLabel(line, text=T("edited_tag"), text_color=th.AMBER, font=th.font(10)).pack(side="right", padx=6)
