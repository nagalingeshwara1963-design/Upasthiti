"""Email sender configuration and admin-only delivery history controls."""
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox
import customtkinter as ctk

from .. import auth
from ..email_service import (PROVIDERS, disconnect_email, get_email_settings,
                             normalize_email, save_email_settings)
from . import theme as th

INITIAL_GMAIL_SENDER = "nagalingeshwara1963@gmail.com"


class EmailSettingsSection(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._build()

    def _build(self):
        if auth.current_role() != "admin": return
        db = self.app.db
        cfg = get_email_settings(db)
        stored_cfg = db.get("email_config", None)
        card = th.card(self); card.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(card, text="Email", font=th.font(14, True), text_color=th.TEXT).pack(anchor="w", padx=16, pady=(12, 3))
        ctk.CTkLabel(card, text="Connect Gmail or Microsoft with OAuth 2.0. Custom SMTP uses STARTTLS/SSL and a protected credential. Gmail can use an app password as a fallback.",
                     wraplength=780, justify="left", text_color=th.GREY, font=th.font(11)).pack(anchor="w", padx=16, pady=(0, 8))
        self.provider = tk.StringVar(value=cfg.get("provider", "Gmail"))
        initial_mode = cfg.get("auth_mode", "oauth" if self.provider.get() in ("Gmail", "Outlook/Microsoft") else "smtp")
        self.auth_mode = tk.StringVar(value=initial_mode)
        initial_sender = (INITIAL_GMAIL_SENDER if stored_cfg is None and cfg.get("provider", "Gmail") == "Gmail"
                          else cfg.get("sender", ""))
        self.sender = tk.StringVar(value=initial_sender)
        self.username = tk.StringVar(value=cfg.get("username", ""))
        self.host = tk.StringVar(value=cfg.get("host", PROVIDERS["Gmail"][0]))
        self.port = tk.StringVar(value=str(cfg.get("port", 587)))
        self.security = tk.StringVar(value=cfg.get("security", "starttls"))
        self.transport = tk.StringVar(value="STARTTLS" if self.security.get() == "starttls" else "SSL/TLS")
        self.secret = tk.StringVar()
        self.client_id = tk.StringVar(value=cfg.get("client_id", ""))
        self.client_secret = tk.StringVar()
        self.tenant = tk.StringVar(value=cfg.get("tenant", "common"))
        self.enabled = tk.BooleanVar(value=cfg["enabled"])
        self.absentee = tk.BooleanVar(value=cfg["absentee_enabled"])
        state_text = (("Connected" if initial_mode == "oauth" else "SMTP configured") + f" — {cfg['sender']}") if cfg["configured"] else "Not connected — add a sender account"
        self.connection = ctk.CTkLabel(card, text=state_text,
                                       text_color=th.GREEN if cfg["configured"] else th.GREY)
        self.connection.pack(anchor="w", padx=16, pady=(0, 6))
        row = ctk.CTkFrame(card, fg_color="transparent"); row.pack(fill="x", padx=16)
        ctk.CTkLabel(row, text="Provider").pack(side="left")
        menu = ctk.CTkOptionMenu(row, values=["Gmail", "Outlook/Microsoft", "SMTP / Other"],
                                 variable=self.provider, command=self._provider_changed, width=185)
        menu.pack(side="left", padx=8)
        self._entry(row, "Sender", self.sender, 245)
        ctk.CTkLabel(row, text="Authentication").pack(side="left", padx=(10, 3))
        self.auth_choice = tk.StringVar(value="OAuth 2.0" if initial_mode == "oauth" else "App password (SMTP)")
        self.auth_menu = ctk.CTkOptionMenu(row, values=["OAuth 2.0", "App password (SMTP)"],
            variable=self.auth_choice,
            command=self._auth_changed, width=175)
        self.auth_menu.pack(side="left")
        self.row2 = ctk.CTkFrame(card, fg_color="transparent")
        self._entry(self.row2, "SMTP login", self.username, 150)
        self._entry(self.row2, "SMTP host", self.host, 250)
        self._entry(self.row2, "Port", self.port, 70)
        ctk.CTkLabel(self.row2, text="Transport").pack(side="left", padx=(12, 4))
        ctk.CTkOptionMenu(self.row2, values=["STARTTLS", "SSL/TLS"], variable=self.transport,
            command=lambda v: self.security.set("starttls" if v == "STARTTLS" else "ssl"), width=110).pack(side="left")
        self.row3 = ctk.CTkFrame(card, fg_color="transparent")
        ctk.CTkLabel(self.row3, text="App password / SMTP credential").pack(side="left")
        ctk.CTkEntry(self.row3, textvariable=self.secret, show="•", width=290,
                     placeholder_text="Leave blank to keep saved credential").pack(side="left", padx=8)
        self.oauth_row = ctk.CTkFrame(card, fg_color="transparent")
        self._entry(self.oauth_row, "OAuth public client ID", self.client_id, 265)
        self.oauth_secret_entry = ctk.CTkEntry(self.oauth_row, textvariable=self.client_secret, show="•", width=170,
                                               placeholder_text="Google client secret (optional)")
        self.oauth_secret_label = ctk.CTkLabel(self.oauth_row, text="Google client secret")
        self.oauth_secret_label.pack(side="left", padx=(8, 3))
        self.oauth_secret_entry.pack(side="left")
        self.tenant_entry = ctk.CTkEntry(self.oauth_row, textvariable=self.tenant, width=145,
                                         placeholder_text="common or tenant ID")
        self.tenant_label = ctk.CTkLabel(self.oauth_row, text="Microsoft tenant")
        self.tenant_label.pack(side="left", padx=(8, 3))
        self.tenant_entry.pack(side="left")
        self.oauth_connect = ctk.CTkButton(self.oauth_row, text="Connect Account", fg_color=th.BLUE,
                                           command=self.connect_oauth)
        self.oauth_connect.pack(side="left", padx=8)
        self.oauth_status = ctk.CTkLabel(card, text="", text_color=th.GREY, wraplength=800, justify="left")
        self.oauth_status.pack(anchor="w", padx=16)
        self.credential_note = ctk.CTkLabel(card, text="Saved credentials and OAuth refresh tokens are protected with Windows DPAPI for this Windows user. OAuth access tokens remain in memory only.",
                     text_color=th.GREY, font=th.font(11), wraplength=780, justify="left")
        self.credential_note.pack(anchor="w", padx=16, pady=(2, 8))
        toggles = ctk.CTkFrame(card, fg_color="transparent"); toggles.pack(fill="x", padx=16)
        ctk.CTkCheckBox(toggles, text="Email enabled", variable=self.enabled).pack(side="left", padx=(0, 18))
        ctk.CTkCheckBox(toggles, text="Automatic absent-student notices (default off)",
                        variable=self.absentee).pack(side="left")
        btns = ctk.CTkFrame(card, fg_color="transparent"); btns.pack(fill="x", padx=16, pady=8)
        ctk.CTkButton(btns, text="Save / Add / Change Sender", fg_color=th.BLUE, command=self.save).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btns, text="Disconnect", fg_color=th.RED, command=self.disconnect).pack(side="left")
        self.test_to = tk.StringVar()
        self.test_status = ctk.CTkLabel(btns, text="", text_color=th.GREY)
        ctk.CTkEntry(btns, textvariable=self.test_to, width=225, placeholder_text="Test recipient email").pack(side="left", padx=(20, 6))
        ctk.CTkButton(btns, text="Send Test Email", fg_color=th.BLUE_LT, text_color=th.BLUE,
                      command=self.test_email).pack(side="left")
        self.test_status.pack(side="left", padx=8)
        ctk.CTkFrame(card, height=1, fg_color=th.BORDER).pack(fill="x", padx=16, pady=6)
        hist = ctk.CTkFrame(card, fg_color="transparent"); hist.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(hist, text="Recent delivery history", font=th.font(12, True), text_color=th.TEXT).pack(anchor="w")
        self.history = ctk.CTkFrame(hist, fg_color="transparent"); self.history.pack(fill="x", pady=4)
        ctk.CTkButton(hist, text="Retry Failed Emails", fg_color=th.BLUE_LT, text_color=th.BLUE,
                      command=self.retry).pack(anchor="w", pady=(4, 0))
        self.render_history()
        self._provider_changed(self.provider.get(), initial=True)

    def _auth_changed(self, value):
        self.auth_mode.set("oauth" if value == "OAuth 2.0" else "smtp")
        self._refresh_auth_controls()

    def _provider_changed(self, provider, initial=False):
        if hasattr(self, "oauth_connect"):
            self.oauth_connect.configure(text="Connect Gmail" if provider == "Gmail" else "Connect Microsoft")
        if provider in PROVIDERS and not initial:
            host, port, security = PROVIDERS[provider]
            self.host.set(host); self.port.set(str(port)); self.security.set(security)
            self.auth_mode.set("oauth")
        elif provider == "SMTP / Other":
            if self.host.get() == PROVIDERS["Gmail"][0]:
                self.host.set("")
            self.auth_mode.set("smtp")
        self._refresh_auth_controls()

    def _refresh_auth_controls(self):
        provider, mode = self.provider.get(), self.auth_mode.get()
        values = ["OAuth 2.0", "App password (SMTP)"] if provider == "Gmail" else (["OAuth 2.0"] if provider == "Outlook/Microsoft" else ["SMTP credential"])
        self.auth_menu.configure(values=values, state="normal" if len(values) > 1 else "disabled")
        self.auth_choice.set("OAuth 2.0" if mode == "oauth" else ("App password (SMTP)" if provider == "Gmail" else "SMTP credential"))
        if mode == "oauth":
            self.row2.pack_forget(); self.row3.pack_forget()
            self.oauth_row.pack(fill="x", padx=16, pady=5)
            self.oauth_secret_entry.pack_forget(); self.oauth_secret_label.pack_forget()
            self.tenant_entry.pack_forget(); self.tenant_label.pack_forget()
            if provider == "Gmail":
                self.oauth_secret_label.pack(side="left", padx=(8, 3)); self.oauth_secret_entry.pack(side="left", padx=4)
            if provider == "Outlook/Microsoft":
                self.tenant_label.pack(side="left", padx=(8, 3)); self.tenant_entry.pack(side="left", padx=4)
        else:
            self.oauth_row.pack_forget()
            self.row2.pack(fill="x", padx=16, pady=5); self.row3.pack(fill="x", padx=16, pady=4)

    def _entry(self, parent, label, var, width):
        ctk.CTkLabel(parent, text=label).pack(side="left", padx=(10, 3))
        ctk.CTkEntry(parent, textvariable=var, width=width).pack(side="left")

    def save(self):
        try:
            if self.absentee.get() and not self.enabled.get():
                raise ValueError("Enable Email before turning on automatic absentee notifications.")
            save_email_settings(self.app.db, provider=self.provider.get(), sender=self.sender.get(),
                                username=self.username.get(), host=self.host.get(), port=self.port.get(),
                                security=self.security.get(), secret=self.secret.get(),
                                enabled=self.enabled.get(), absentee_enabled=self.absentee.get(),
                                auth_mode=self.auth_mode.get(), client_id=self.client_id.get(),
                                client_secret=self.client_secret.get(), tenant=self.tenant.get())
            self.secret.set("")
            cfg = get_email_settings(self.app.db)
            self.connection.configure(text=self._connection_text(cfg),
                                      text_color=th.GREEN if cfg["configured"] else th.GREY)
            messagebox.showinfo("Upasthiti", "Email settings saved. Send a test email to verify provider access.", parent=self)
        except Exception as exc:
            messagebox.showwarning("Upasthiti", str(exc), parent=self)

    @staticmethod
    def _connection_text(cfg):
        if not cfg["configured"]: return "Not connected — add a sender account"
        return ("Connected" if cfg.get("auth_mode") == "oauth" else "SMTP configured") + f" — {cfg['sender']}"

    def connect_oauth(self):
        provider = self.provider.get()
        try:
            if self.auth_mode.get() != "oauth" or provider not in ("Gmail", "Outlook/Microsoft"):
                raise ValueError("Choose Gmail or Outlook/Microsoft with OAuth 2.0.")
            desired_email, desired_absentee = self.enabled.get(), self.absentee.get()
            self.enabled.set(False); self.absentee.set(False)
            save_email_settings(self.app.db, provider=provider, sender=self.sender.get(), username=self.username.get(),
                host=self.host.get(), port=self.port.get(), security=self.security.get(), secret="",
                enabled=False, absentee_enabled=False, auth_mode="oauth", client_id=self.client_id.get(),
                client_secret=self.client_secret.get(), tenant=self.tenant.get())
            self.app.db.put("email_enabled", False); self.app.db.put("email_absentee_enabled", False)
            self.oauth_connect.configure(state="disabled")
            self.oauth_status.configure(text="Starting provider authorization…", text_color=th.BLUE)
        except Exception as exc:
            messagebox.showwarning("Upasthiti", str(exc), parent=self); return

        def progress(text):
            self.app.post(lambda: self._oauth_progress(text))

        client_id = self.client_id.get()
        client_secret = self.client_secret.get()
        tenant = self.tenant.get()
        def work():
            try:
                account = self.app.email_service.connect_oauth(provider, client_id, client_secret, tenant, progress)
                self.app.post(lambda value=account: self._oauth_connected(desired_email, desired_absentee, value))
            except Exception as exc:
                safe_text = str(exc)[:280]
                self.app.post(lambda text=safe_text: self._oauth_failed(text))
        threading.Thread(target=work, name="UpasthitiEmailOAuth", daemon=True).start()

    def _oauth_progress(self, text):
        if self.winfo_exists(): self.oauth_status.configure(text=text, text_color=th.BLUE)

    def _oauth_connected(self, desired_email, desired_absentee, account=None):
        if not self.winfo_exists(): return
        self.oauth_connect.configure(state="normal")
        identity = account if account and self.provider.get() == "Gmail" else self.sender.get()
        self.connection.configure(text=f"Connected — {identity}", text_color=th.GREEN)
        self.oauth_status.configure(text="Provider authorization complete. The refresh token is protected with Windows DPAPI; short-lived access tokens stay in memory.",
                                    text_color=th.GREEN)
        if desired_email:
            self.enabled.set(True); self.absentee.set(desired_absentee)
            self.save()

    def _oauth_failed(self, text):
        if not self.winfo_exists(): return
        self.oauth_connect.configure(state="normal")
        self.oauth_status.configure(text="Authorization failed: " + text, text_color=th.RED)

    def disconnect(self):
        if not messagebox.askyesno("Upasthiti", "Remove the saved sender account and protected credential?", parent=self): return
        disconnect_email(self.app.db)
        self.secret.set(""); self.client_secret.set(""); self.enabled.set(False); self.absentee.set(False)
        self.connection.configure(text="Not connected — add a sender account", text_color=th.GREY)
        self.oauth_status.configure(text="Sender removed. Student recipients, attendance, and reports were kept.", text_color=th.GREY)
        self.app.notify_changed()

    def test_email(self):
        try:
            recipient = normalize_email(self.test_to.get())
            if not get_email_settings(self.app.db)["configured"]:
                raise ValueError("Configure and save a sender first.")
            self.test_status.configure(text="Test queued…", text_color=th.BLUE)
            delivery_id = self.app.email_service.send_test_email(recipient)
            self._poll_test(delivery_id)
        except Exception as exc:
            self.test_status.configure(text="Test failed", text_color=th.RED)
            messagebox.showwarning("Upasthiti", str(exc), parent=self)

    def _poll_test(self, delivery_id):
        row = self.app.db.email_delivery(delivery_id)
        if not row: return
        if row["status"] in ("pending", "sending"):
            self.after(500, lambda: self._poll_test(delivery_id)); return
        if row["status"] == "sent":
            self.test_status.configure(text="✓ Provider accepted test", text_color=th.GREEN)
        else:
            self.test_status.configure(text="⚠ Test failed", text_color=th.RED)
            messagebox.showwarning("Upasthiti", row["failure"] or "Email was not sent.", parent=self)
        self.render_history()

    def retry(self):
        ids = self.app.email_service.retry_failed()
        if ids:
            messagebox.showinfo("Upasthiti", f"Retrying {len(ids)} failed email(s) in the background.", parent=self)
        else:
            messagebox.showinfo("Upasthiti", "There are no retryable failed emails.", parent=self)
        self.render_history()

    def render_history(self):
        for w in self.history.winfo_children(): w.destroy()
        for row in self.app.db.list_email_deliveries(20):
            recipient = row["recipient"] or "No recipient"
            status = "Provider accepted" if row["status"] == "sent" else row["status"].replace("_", " ").title()
            when = datetime.fromtimestamp(row["updated_at"]).strftime("%d %b %Y %H:%M")
            detail = f"{when} — {row['kind'].replace('_', ' ').title()} — {row['student_name'] or row['student_code'] or ''} — {recipient} — {status}"
            if row["failure"]: detail += f" — {row['failure'][:110]}"
            ctk.CTkLabel(self.history, text=detail, anchor="w", wraplength=820, justify="left",
                         text_color=th.RED if row["status"] == "failed" else th.GREY,
                         font=th.font(10)).pack(fill="x", pady=1)
