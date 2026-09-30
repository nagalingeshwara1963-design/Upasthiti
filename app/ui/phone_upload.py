"""Shared desktop dialog for short-lived phone photo upload sessions."""
import customtkinter as ctk

from .. import config
from ..phone_upload import PhoneUploadError, PhoneUploadSession, make_qr_image
from . import theme as th


class PhoneUploadDialog(ctk.CTkToplevel):
    def __init__(self, parent, on_received, capture_context=None, on_analysis=None):
        super().__init__(parent)
        self.page = parent
        self.app = parent.app
        self.on_received = on_received
        self.on_analysis = on_analysis
        self.analyzer = None
        self.session = None
        self._ending = False
        self.title("Smart Capture from Phone" if capture_context else "Upload Photos from Phone")
        self.geometry("800x700")
        self.minsize(660, 600)
        self.transient(parent.winfo_toplevel())
        self.configure(fg_color=th.BG)

        card = th.card(self)
        card.pack(fill="both", expand=True, padx=18, pady=18)
        heading = "Smart Capture from Phone" if capture_context else "Upload Photos from Phone"
        closing_note = "The laptop analyzes captures; you decide when to finish and review." if capture_context else "Photos are transferred to this laptop for the existing enrollment workflow."
        ctk.CTkLabel(card, text=heading, font=th.font(20, True), text_color=th.BLUE_DK).pack(anchor="w", padx=20, pady=(18, 4))
        ctk.CTkLabel(card, text="1. Connect both devices to the same local network.\n2. Scan the QR code.\n3. Preview and choose photos on the phone before uploading.\n\n" + closing_note,
                     font=th.font(12), text_color=th.GREY, justify="left").pack(anchor="w", padx=20, pady=(0, 12))

        self.adapter_row = ctk.CTkFrame(card, fg_color="transparent")
        self.adapter_row.pack(fill="x", padx=20)
        ctk.CTkLabel(self.adapter_row, text="Laptop network address", text_color=th.GREY).pack(side="left")
        self.adapter = ctk.CTkOptionMenu(self.adapter_row, values=["Starting…"], command=self._choose_endpoint,
                                         fg_color=th.BLUE, button_color=th.BLUE_DK, width=210)
        self.adapter.pack(side="right")

        middle = ctk.CTkFrame(card, fg_color="transparent")
        middle.pack(fill="both", expand=True, padx=20, pady=8)
        self.qr_label = ctk.CTkLabel(middle, text="Preparing a temporary upload session…", text_color=th.GREY, width=290, height=290)
        self.qr_label.pack(side="left", padx=(6, 22), pady=8)
        right = ctk.CTkFrame(middle, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)
        self.url_label = ctk.CTkLabel(right, text="", wraplength=320, justify="left", text_color=th.BLUE, font=th.font(11))
        self.url_label.pack(anchor="w", pady=(10, 8))
        ctk.CTkLabel(right, text="Status", font=th.font(12, True), text_color=th.TEXT).pack(anchor="w", pady=(8, 2))
        self.status_label = ctk.CTkLabel(right, text="Starting…", font=th.font(13, True), text_color=th.BLUE, anchor="w")
        self.status_label.pack(anchor="w")
        self.count_label = ctk.CTkLabel(right, text="Photos received: 0", text_color=th.TEXT, anchor="w")
        self.count_label.pack(anchor="w", pady=(8, 2))
        self.expiry_label = ctk.CTkLabel(right, text="Session expires in: 15:00", text_color=th.GREY, anchor="w")
        self.expiry_label.pack(anchor="w")
        summary_text = "Smart Capture\nWaiting for photos." if capture_context else "Photos are added to enrollment when you finish."
        self.capture_summary = ctk.CTkLabel(right, text=summary_text, text_color=th.GREY,
                                            justify="left", anchor="w", wraplength=270)
        self.capture_summary.pack(anchor="w", fill="x", pady=(8, 0))
        ctk.CTkLabel(right, text="If the page will not open, check that the phone is not on guest Wi-Fi or mobile data. A firewall may need to allow Upasthiti on a private network.",
                     wraplength=320, justify="left", text_color=th.GREY, font=th.font(11)).pack(anchor="w", pady=(14, 0))

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(fill="x", padx=20, pady=(4, 18))
        self.finish_button = ctk.CTkButton(actions, text="Finish Anyway / Review" if capture_context else "Finish / Continue",
                                           command=self.finish,
                                           fg_color=th.GREEN, hover_color="#1B5E20", state="disabled")
        self.finish_button.pack(side="right", padx=(8, 0))
        self.cancel_button = ctk.CTkButton(actions, text="Cancel", command=self.cancel,
                                           fg_color=th.GREY, hover_color="#46505A")
        self.cancel_button.pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        right.bind("<Configure>", lambda event: self.capture_summary.configure(wraplength=max(210, event.width - 8)))

        try:
            self.session = PhoneUploadSession(config.PHONE_UPLOAD_DIR)
            if capture_context:
                from ..smart_capture import SmartCaptureAnalyzer
                self.analyzer = SmartCaptureAnalyzer(
                    capture_context["service"], capture_context["class_id"], capture_context["mode"],
                    capture_context["config"], capture_context.get("initial_photos", ()),
                    on_update=self.session.set_analysis_status)
                self.session.set_upload_callback(self.analyzer.submit)
            self._endpoints = self.session.endpoints
            values = [f"{x['address']}:{x['port']}" for x in self._endpoints]
            self.adapter.configure(values=values)
            self.adapter.set(values[0])
            self.finish_button.configure(state="normal")
            self._show_endpoint(0)
            self._tick()
        except PhoneUploadError as exc:
            self.status_label.configure(text=str(exc), text_color=th.RED, wraplength=340)
            self.qr_label.configure(text="No upload session started", image=None)
        except Exception:
            self.status_label.configure(text="Could not start phone upload. Check the laptop network and try again.", text_color=th.RED, wraplength=340)
            self.qr_label.configure(text="No upload session started", image=None)

    def _choose_endpoint(self, value):
        for i, endpoint in enumerate(getattr(self, "_endpoints", [])):
            if value == f"{endpoint['address']}:{endpoint['port']}":
                self._show_endpoint(i)
                return

    def _show_endpoint(self, index):
        endpoint = self._endpoints[index]
        url = endpoint["url"]
        try:
            image = ctk.CTkImage(light_image=make_qr_image(url), size=(288, 288))
            self.qr_label.configure(image=image, text="")
            self.qr_label._qr_image = image
        except Exception:
            self.qr_label.configure(image=None, text="QR display is unavailable.\nOpen the local URL shown here.")
        self.url_label.configure(text=url)

    def _tick(self):
        if not self.winfo_exists() or self.session is None or self._ending:
            return
        status = self.session.status()
        if status.get("finish_requested") and status["state"] == "active":
            self.finish()
            return
        if status["state"] == "expired":
            self.status_label.configure(text="Session expired — start a new upload session.", text_color=th.RED)
            self.finish_button.configure(state="disabled")
        else:
            analysis = status.get("analysis", {})
            if status["uploading"]:
                text, color = "Uploading photos…", th.BLUE
            elif analysis.get("state") == "analyzing":
                text, color = "Analyzing on laptop…", th.BLUE
            elif status["count"]:
                text, color = "Photos received — capture more or finish", th.GREEN
            elif status["connected"]:
                text, color = "Phone connected — waiting for photos", th.BLUE
            else:
                text, color = "Waiting for phone", th.GREY
            self.status_label.configure(text=text, text_color=color)
            self.count_label.configure(text=f"Photos received: {status['count']}")
            remaining = status["expires_in"]
            self.expiry_label.configure(text=f"Session expires in: {remaining // 60:02d}:{remaining % 60:02d}")
            if analysis.get("photos_analyzed") or analysis.get("state") not in (None, "waiting"):
                self.capture_summary.configure(text=(
                    f"Detected faces: {analysis.get('detected_faces', 0)}\n"
                    f"Confidently observed: {analysis.get('confidently_observed', 0)} / {analysis.get('total_students', 0)}\n"
                    f"Uncertain students: {analysis.get('uncertain_students', 0)} · Unknown faces: {analysis.get('unknown_faces', 0)}\n"
                    f"Not yet observed: {analysis.get('not_yet_observed', 0)} · Coverage: {analysis.get('coverage_percent', 0)}%\n"
                    f"Recommendation: {analysis.get('guidance', 'Analyzing…')}"),
                    text_color=th.AMBER if analysis.get("another_capture_suggested") else th.GREEN)
        self.after(1000, self._tick)

    def finish(self):
        if self.session is None or self._ending or self.session.status()["state"] != "active":
            return
        self._ending = True
        self.finish_button.configure(state="disabled")
        self.cancel_button.configure(state="disabled")
        self.status_label.configure(text="Closing upload link…", text_color=th.BLUE)

        def ready(paths, cleanup):
            if self.analyzer:
                self.app.post(lambda: self.status_label.configure(text="Finishing laptop analysis before opening review…", text_color=th.BLUE))
                self.analyzer.finish(lambda result: self.app.post(lambda: self._deliver(paths, cleanup, result)))
            else:
                self.app.post(lambda: self._deliver(paths, cleanup, None))

        self.session.close(delete=False, callback=ready, reason="finished")

    def _deliver(self, paths, cleanup, result=None):
        if self.on_analysis and result:
            self.on_analysis(result)
        if self.winfo_exists():
            self.destroy()
        self.on_received(paths, cleanup)

    def cancel(self):
        if self._ending:
            return
        self._ending = True
        if self.analyzer: self.analyzer.cancel()
        if self.session is not None:
            self.session.close(delete=True, reason="cancelled")
        self.destroy()
