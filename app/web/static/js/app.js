/**
 * Upasthiti Web Application — Complete JavaScript Controller
 * Faithfully powers the browser edition of Upasthiti with desktop parity.
 */

// Application State
const state = {
  user: null,
  role: null,
  studentId: null,
  isDemo: false,
  classes: [],
  activeClassId: null,
  currentPage: "home",
  stagedPhotos: [],
  activePhoneSession: null,
  phonePollInterval: null,
  recognitionResult: null,
  enrollWebcamStream: null,
};

// ------------------ INITIALIZATION ------------------
document.addEventListener("DOMContentLoaded", async () => {
  setupEventListeners();
  await checkAuthSession();
});

async function checkAuthSession() {
  try {
    const res = await fetch("/api/auth/me");
    if (res.ok) {
      const data = await res.json();
      setAuthenticatedUser(data);
      await loadInitialData();
    } else {
      showLoginScreen();
    }
  } catch (err) {
    console.error("Auth check failed:", err);
    showLoginScreen();
  }
}

function showLoginScreen() {
  document.getElementById("login-container").style.display = "flex";
  document.getElementById("app-shell").style.display = "none";
}

function showAppShell() {
  document.getElementById("login-container").style.display = "none";
  document.getElementById("app-shell").style.display = "flex";
}

function setAuthenticatedUser(profile) {
  state.user = profile.user;
  state.role = profile.role;
  state.studentId = profile.student_id;
  state.isDemo = profile.is_demo;

  // Update user badge in sidebar
  const badge = document.getElementById("user-display-badge");
  if (state.role === "student") {
    badge.textContent = `👤 ${state.user} (Student)`;
    document.getElementById("staff-nav-list").style.display = "none";
    document.getElementById("student-nav-list").style.display = "block";
    document.getElementById("class-selector-wrapper").style.display = "none";
  } else {
    badge.textContent = `👤 ${state.user} (${state.role})`;
    document.getElementById("staff-nav-list").style.display = "block";
    document.getElementById("student-nav-list").style.display = "none";
    document.getElementById("class-selector-wrapper").style.display = "flex";
  }

  // Toggle admin-only controls
  document.querySelectorAll(".admin-only").forEach(el => {
    el.style.display = state.role === "admin" ? "" : "none";
  });

  // Demo indicator
  document.getElementById("demo-indicator").style.display = state.isDemo ? "block" : "none";

  showAppShell();
  if (state.role === "student") {
    navigatePage("student-portal");
  } else {
    navigatePage("home");
  }
}

// ------------------ EVENT LISTENERS SETUP ------------------
function setupEventListeners() {
  // Login Role Change
  document.getElementById("login-role").addEventListener("change", (e) => {
    const role = e.target.value;
    const isStudent = role === "Student";
    document.getElementById("login-staff-fields").style.display = isStudent ? "none" : "block";
    document.getElementById("login-student-fields").style.display = isStudent ? "block" : "none";
    document.getElementById("login-error-msg").textContent = "";
  });

  // Login Submit
  document.getElementById("btn-do-login").addEventListener("click", handleLogin);
  document.getElementById("login-pw").addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleLogin();
  });
  document.getElementById("login-student-pw").addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleLogin();
  });

  // Demo Mode
  document.getElementById("btn-enter-demo").addEventListener("click", handleEnterDemo);
  document.getElementById("btn-exit-demo").addEventListener("click", handleExitDemo);

  // Logout
  document.getElementById("btn-do-logout").addEventListener("click", handleLogout);

  // Mobile Menu Toggle
  document.getElementById("mobile-toggle-btn").addEventListener("click", () => {
    document.getElementById("sidebar").classList.toggle("open");
  });

  // Navigation Items
  document.querySelectorAll(".nav-item").forEach(btn => {
    btn.addEventListener("click", () => {
      const page = btn.dataset.page;
      navigatePage(page);
      document.getElementById("sidebar").classList.remove("open");
    });
  });

  // Class Dropdown Change
  document.getElementById("active-class-select").addEventListener("change", (e) => {
    state.activeClassId = parseInt(e.target.value) || null;
    onClassChanged();
  });

  // New Class
  document.getElementById("btn-open-new-class-modal").addEventListener("click", () => {
    openModal("modal-new-class");
  });
  document.getElementById("btn-submit-new-class").addEventListener("click", handleCreateClass);

  // Group Photos Browse & Clear
  document.getElementById("btn-group-browse").addEventListener("click", () => {
    document.getElementById("group-file-input").click();
  });
  document.getElementById("group-file-input").addEventListener("change", handleGroupPhotosUpload);
  document.getElementById("btn-clear-staged").addEventListener("click", handleClearStagedPhotos);
  document.getElementById("btn-group-phone").addEventListener("click", openPhoneUploadDialog);
  document.getElementById("btn-quick-phone").addEventListener("click", openPhoneUploadDialog);

  // Attendance Controls
  document.getElementById("btn-run-attendance").addEventListener("click", handleRunAttendance);
  document.getElementById("btn-save-final-attendance").addEventListener("click", handleSaveFinalAttendance);
  document.getElementById("check-auto-threshold").addEventListener("change", (e) => {
    const slider = document.getElementById("threshold-slider");
    slider.disabled = e.target.checked;
    updateThresholdHint();
  });
  document.getElementById("threshold-slider").addEventListener("input", updateThresholdHint);

  // Enrollment Controls
  document.getElementById("btn-enroll-browse").addEventListener("click", () => {
    document.getElementById("enroll-file-input").click();
  });
  document.getElementById("enroll-file-input").addEventListener("change", handleEnrollPhotoSelected);
  document.getElementById("btn-enroll-camera").addEventListener("click", toggleEnrollWebcam);
  document.getElementById("btn-enroll-snap").addEventListener("click", captureEnrollWebcamPhoto);
  document.getElementById("btn-save-student").addEventListener("click", handleSaveStudent);
  document.getElementById("btn-open-rebuild-gallery").addEventListener("click", handleRebuildGallery);

  // Reports Exports
  document.getElementById("btn-export-csv").addEventListener("click", () => {
    if (!state.activeClassId) return alert("Select a class first.");
    window.location.href = `/api/reports/export/csv?class_id=${state.activeClassId}`;
  });
  document.getElementById("btn-export-audit").addEventListener("click", () => {
    window.location.href = "/api/reports/export/audit_csv";
  });

  // Email Center
  document.getElementById("btn-email-preview-selected").addEventListener("click", handlePreviewEmail);
  document.getElementById("btn-email-send-selected").addEventListener("click", handleSendEmail);

  // Recovery Calculator & Assistant
  document.getElementById("btn-calc-recovery").addEventListener("click", handleCalculateRecovery);
  document.getElementById("btn-ask-assistant").addEventListener("click", handleAskAssistant);
  document.getElementById("assistant-question-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleAskAssistant();
  });

  // Settings
  const btnSaveSettings = document.getElementById("btn-save-settings");
  if (btnSaveSettings) btnSaveSettings.addEventListener("click", handleSaveSettings);

  const btnCreateBackup = document.getElementById("btn-create-backup");
  if (btnCreateBackup) btnCreateBackup.addEventListener("click", handleCreateBackup);

  // Phone Upload Modal
  document.getElementById("btn-finish-phone-session").addEventListener("click", handleFinishPhoneSession);

  // Student Review Claim Submission
  document.getElementById("btn-submit-review-claim").addEventListener("click", handleSubmitReviewClaim);
}

// ------------------ AUTH & DEMO ACTIONS ------------------

async function handleLogin() {
  const role = document.getElementById("login-role").value;
  const errMsg = document.getElementById("login-error-msg");
  errMsg.textContent = "";

  const payload = {
    role: role,
    username: document.getElementById("login-user").value,
    password: role === "Student" ? document.getElementById("login-student-pw").value : document.getElementById("login-pw").value,
    student_name: document.getElementById("login-student-name").value,
    student_code: document.getElementById("login-student-code").value,
  };

  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      errMsg.textContent = data.detail || "Authentication failed.";
      return;
    }

    if (data.must_change_password) {
      const newPw = prompt("Please choose a new permanent password (10–256 characters):");
      if (newPw) {
        await fetch("/api/auth/student-change-password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ new_password: newPw }),
        });
      }
    }

    setAuthenticatedUser(data);
    await loadInitialData();
  } catch (err) {
    errMsg.textContent = "Unable to connect to Upasthiti server.";
  }
}

async function handleEnterDemo() {
  try {
    const res = await fetch("/api/demo/enter", { method: "POST" });
    const data = await res.json();
    if (res.ok) {
      setAuthenticatedUser(data);
      await loadInitialData();
    }
  } catch (err) {
    alert("Could not start demo mode: " + err);
  }
}

async function handleExitDemo() {
  if (!confirm("Exit Demo Mode and discard temporary synthetic records?")) return;
  try {
    await fetch("/api/demo/exit", { method: "POST" });
    window.location.reload();
  } catch (err) {
    window.location.reload();
  }
}

async function handleLogout() {
  if (state.isDemo) {
    handleExitDemo();
    return;
  }
  if (!confirm("Are you sure you want to log out?")) return;
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } finally {
    window.location.reload();
  }
}

// ------------------ DATA LOADING & NAVIGATION ------------------

async function loadInitialData() {
  await loadClasses();
  await loadStagedPhotos();
  if (state.role === "student") {
    await loadStudentPortalData();
  } else {
    await refreshCurrentPage();
  }
}

async function loadClasses() {
  try {
    const res = await fetch("/api/classes");
    if (res.ok) {
      state.classes = await res.json();
      const menu = document.getElementById("active-class-select");
      menu.innerHTML = "";
      if (state.classes.length === 0) {
        menu.innerHTML = `<option value="">(No assigned classes)</option>`;
        state.activeClassId = null;
      } else {
        state.classes.forEach(c => {
          const opt = document.createElement("option");
          opt.value = c.id;
          opt.textContent = c.name;
          menu.appendChild(opt);
        });
        if (!state.activeClassId || !state.classes.find(c => c.id === state.activeClassId)) {
          state.activeClassId = state.classes[0].id;
        }
        menu.value = state.activeClassId;
      }
    }
  } catch (err) {
    console.error("Could not load classes:", err);
  }
}

function onClassChanged() {
  refreshCurrentPage();
}

function navigatePage(pageKey) {
  state.currentPage = pageKey;

  // Update active state in nav
  document.querySelectorAll(".nav-item").forEach(item => {
    item.classList.toggle("active", item.dataset.page === pageKey);
  });

  // Hide all views
  document.querySelectorAll(".page-view").forEach(view => {
    view.style.display = "none";
  });

  // Page titles map matching desktop T()
  const titleMap = {
    home: "Home",
    enroll: "Enroll Students",
    photos: "Group Photos",
    attendance: "Attendance",
    reports: "Reports",
    email_center: "Email Center",
    recovery: "Recovery",
    reviews: "Review Requests",
    settings: "Settings",
    models: "Models & Licences",
    help: "Help",
    "student-portal": "Student Portal",
    "student-history": "My Attendance History",
    "student-reviews": "My Review Requests",
    "student-chat": "Local Assistant",
  };

  document.getElementById("current-page-title").textContent = titleMap[pageKey] || "Upasthiti";

  const targetView = document.getElementById(`view-${pageKey}`);
  if (targetView) {
    targetView.style.display = "block";
  }

  refreshCurrentPage();
}

async function refreshCurrentPage() {
  switch (state.currentPage) {
    case "home":
      await loadHomeStats();
      break;
    case "enroll":
      await loadEnrolledStudents();
      break;
    case "photos":
      await loadStagedPhotos();
      break;
    case "attendance":
      await setupAttendancePage();
      break;
    case "reports":
      await loadReportsList();
      break;
    case "email_center":
      await loadEmailCenter();
      break;
    case "reviews":
      await loadReviewRequestsQueue();
      break;
    case "student-portal":
    case "student-history":
    case "student-reviews":
    case "student-chat":
      await loadStudentPortalData();
      break;
  }
}

// ------------------ 1. HOME DASHBOARD ------------------

async function loadHomeStats() {
  if (!state.activeClassId) return;
  try {
    const res = await fetch("/api/health");
    if (res.ok) {
      const data = await res.json();
      document.getElementById("stat-students").textContent = data.stats.students || 0;
      document.getElementById("stat-sessions-today").textContent = data.stats.sessions || 0;
    }

    const sessRes = await fetch(`/api/reports/sessions?class_id=${state.activeClassId}`);
    if (sessRes.ok) {
      const sessions = await sessRes.json();
      const listEl = document.getElementById("home-today-sessions-list");
      listEl.innerHTML = "";
      if (sessions.length === 0) {
        listEl.innerHTML = `<div style="color: var(--grey); font-size: 13px;">No attendance recorded today for this class.</div>`;
      } else {
        sessions.slice(0, 5).forEach(s => {
          const div = document.createElement("div");
          div.style = "display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--border);";
          div.innerHTML = `
            <div>
              <strong>${s.subject || "General"}</strong> (${s.time})
              <span class="badge ${s.pct >= 75 ? "badge-present" : "badge-absent"}">${s.pct}%</span>
            </div>
            <button class="btn btn-secondary btn-sm" onclick="navigatePage('reports')">Open</button>
          `;
          listEl.appendChild(div);
        });
      }
    }
  } catch (err) {
    console.error("Home stats error:", err);
  }
}

// ------------------ 2. ENROLLMENT ------------------

async function loadEnrolledStudents() {
  if (!state.activeClassId) return;
  try {
    const res = await fetch(`/api/classes/${state.activeClassId}/students`);
    if (res.ok) {
      const students = await res.json();
      const tbody = document.getElementById("enrolled-students-tbody");
      tbody.innerHTML = "";
      if (students.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--grey);">No students enrolled in this class yet.</td></tr>`;
        return;
      }
      students.forEach(s => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><strong>${s.code}</strong></td>
          <td>${s.name}</td>
          <td>${s.enrolled_faces || 0} photo(s)</td>
          <td>
            <button class="btn btn-danger-lt btn-sm" onclick="handleArchiveStudent('${s.code}')">Archive</button>
          </td>
        `;
        tbody.appendChild(tr);
      });
    }
  } catch (err) {
    console.error("Could not load enrolled students:", err);
  }
}

let enrolledPhotoData = null;

function handleEnrollPhotoSelected(e) {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (event) => {
    enrolledPhotoData = event.target.result;
    document.getElementById("enroll-preview-img").src = enrolledPhotoData;
    document.getElementById("enroll-preview-img").style.display = "block";
    document.getElementById("enroll-webcam-video").style.display = "none";
    document.getElementById("enroll-preview-hint").style.display = "none";
  };
  reader.readAsDataURL(file);
}

async function toggleEnrollWebcam() {
  const video = document.getElementById("enroll-webcam-video");
  const snapBtn = document.getElementById("btn-enroll-snap");
  const hint = document.getElementById("enroll-preview-hint");
  const img = document.getElementById("enroll-preview-img");

  if (state.enrollWebcamStream) {
    state.enrollWebcamStream.getTracks().forEach(t => t.stop());
    state.enrollWebcamStream = null;
    video.style.display = "none";
    snapBtn.style.display = "none";
    hint.style.display = "block";
    return;
  }

  try {
    state.enrollWebcamStream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
    video.srcObject = state.enrollWebcamStream;
    video.style.display = "block";
    img.style.display = "none";
    hint.style.display = "none";
    snapBtn.style.display = "inline-flex";
  } catch (err) {
    alert("Could not access camera: " + err.message);
  }
}

function captureEnrollWebcamPhoto() {
  const video = document.getElementById("enroll-webcam-video");
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth || 640;
  canvas.height = video.videoHeight || 480;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  enrolledPhotoData = canvas.toDataURL("image/jpeg", 0.95);

  document.getElementById("enroll-preview-img").src = enrolledPhotoData;
  document.getElementById("enroll-preview-img").style.display = "block";
  toggleEnrollWebcam();
}

async function handleSaveStudent() {
  if (!state.activeClassId) return alert("Select a class first.");
  const code = document.getElementById("enroll-code").value.trim();
  const name = document.getElementById("enroll-name").value.trim();
  const email = document.getElementById("enroll-email").value.trim();
  const statusEl = document.getElementById("enroll-status-msg");

  if (!code || !name) {
    statusEl.style.color = "var(--red)";
    statusEl.textContent = "Student ID and Name are required.";
    return;
  }

  statusEl.style.color = "var(--blue)";
  statusEl.textContent = "Saving student and embedding face...";

  try {
    // 1. Create student
    const sRes = await fetch(`/api/classes/${state.activeClassId}/students`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, name, email }),
    });
    if (!sRes.ok) {
      const err = await sRes.json();
      throw new Error(err.detail || "Could not create student");
    }

    // 2. Enroll photo if present
    if (enrolledPhotoData) {
      const form = new FormData();
      form.append("image_base64", enrolledPhotoData);
      const eRes = await fetch(`/api/classes/${state.activeClassId}/students/${code}/enroll`, {
        method: "POST",
        body: form,
      });
      if (!eRes.ok) {
        const err = await eRes.json();
        throw new Error(err.detail || "Could not enroll photo");
      }
    }

    statusEl.style.color = "var(--green)";
    statusEl.textContent = `Student ${name} (${code}) saved successfully!`;
    document.getElementById("enroll-code").value = "";
    document.getElementById("enroll-name").value = "";
    document.getElementById("enroll-email").value = "";
    enrolledPhotoData = null;
    document.getElementById("enroll-preview-img").style.display = "none";
    document.getElementById("enroll-preview-hint").style.display = "block";
    await loadEnrolledStudents();
  } catch (err) {
    statusEl.style.color = "var(--red)";
    statusEl.textContent = err.message;
  }
}

async function handleArchiveStudent(code) {
  if (!confirm(`Archive student ${code}? Historical attendance records will be preserved.`)) return;
  try {
    await fetch(`/api/classes/${state.activeClassId}/students/${code}`, { method: "DELETE" });
    await loadEnrolledStudents();
  } catch (err) {
    alert("Could not archive student: " + err);
  }
}

async function handleRebuildGallery() {
  if (!state.activeClassId) return alert("Select a class first.");
  if (!confirm("Rebuild recognition gallery from all enrolled student photos?")) return;
  try {
    const res = await fetch(`/api/classes/${state.activeClassId}/gallery/rebuild`, { method: "POST" });
    const data = await res.json();
    alert(data.message || "Gallery rebuilt successfully.");
  } catch (err) {
    alert("Rebuild failed: " + err);
  }
}

// ------------------ 3. GROUP PHOTOS & STAGED QUEUE ------------------

async function loadStagedPhotos() {
  try {
    const res = await fetch("/api/photos/staged");
    if (res.ok) {
      state.stagedPhotos = await res.json();
      renderStagedPhotos();
    }
  } catch (err) {
    console.error("Could not load staged photos:", err);
  }
}

function renderStagedPhotos() {
  const container = document.getElementById("staged-photos-container");
  const countBadge = document.getElementById("staged-count-badge");
  countBadge.textContent = `${state.stagedPhotos.length} photo(s) ready`;

  const attendHint = document.getElementById("attendance-photo-hint");
  if (attendHint) {
    if (state.stagedPhotos.length > 0) {
      attendHint.style.color = "var(--green)";
      attendHint.textContent = `✓ ${state.stagedPhotos.length} group photo(s) staged and ready`;
    } else {
      attendHint.style.color = "var(--amber)";
      attendHint.textContent = "⚠ Add group photos in Group Photos tab first";
    }
  }

  container.innerHTML = "";
  if (state.stagedPhotos.length === 0) {
    container.innerHTML = `
      <div style="grid-column: 1 / -1; text-align: center; color: var(--grey); padding: 40px 0;">
        No group photos staged yet. Add photos from your computer or scan with phone.
      </div>
    `;
    return;
  }

  state.stagedPhotos.forEach((p, idx) => {
    const card = document.createElement("div");
    card.className = "staged-card";
    card.innerHTML = `
      <img src="${p.thumbnail}" alt="Classroom Photo">
      <div style="font-size: 11px; color: var(--grey); margin: 6px 0;">${p.label} (${p.width}×${p.height})</div>
      <button class="btn btn-danger-lt btn-sm" style="width: 100%;" onclick="handleRemoveStagedPhoto(${idx})">Remove</button>
    `;
    container.appendChild(card);
  });
}

async function handleGroupPhotosUpload(e) {
  const files = e.target.files;
  if (!files || files.length === 0) return;

  for (let i = 0; i < files.length; i++) {
    const form = new FormData();
    form.append("file", files[i]);
    form.append("zone", "Whole class");
    await fetch("/api/photos/staged/upload", { method: "POST", body: form });
  }

  await loadStagedPhotos();
}

async function handleRemoveStagedPhoto(idx) {
  await fetch(`/api/photos/staged/${idx}`, { method: "DELETE" });
  await loadStagedPhotos();
}

async function handleClearStagedPhotos() {
  if (!confirm("Clear all staged photos?")) return;
  await fetch("/api/photos/staged/clear", { method: "POST" });
  await loadStagedPhotos();
}

// ------------------ 4. QR PHONE SMART CAPTURE ------------------

async function openPhoneUploadDialog() {
  if (!state.activeClassId) return alert("Select a class first.");
  try {
    const form = new FormData();
    form.append("class_id", state.activeClassId);
    const res = await fetch("/api/phone_upload/start", { method: "POST", body: form });
    if (!res.ok) throw new Error("Could not start phone session");
    const data = await res.json();
    state.activePhoneSession = data;

    document.getElementById("qr-code-img").src = data.qr_code;
    document.getElementById("qr-session-url").textContent = data.phone_url;
    document.getElementById("qr-session-status").textContent = "Waiting for phone to scan QR code...";

    openModal("modal-phone-qr");
    startPhonePolling(data.token);
  } catch (err) {
    alert("Phone session error: " + err);
  }
}

function startPhonePolling(token) {
  if (state.phonePollInterval) clearInterval(state.phonePollInterval);
  state.phonePollInterval = setInterval(async () => {
    try {
      const res = await fetch(`/phone_upload/${token}/status`);
      if (res.ok) {
        const data = await res.json();
        const statusEl = document.getElementById("qr-session-status");
        if (data.files_count > 0) {
          statusEl.textContent = `✓ ${data.files_count} photo(s) received from phone!`;
          await loadStagedPhotos();
        }
      }
    } catch (e) {
      console.warn("Phone poll error:", e);
    }
  }, 2500);
}

async function handleFinishPhoneSession() {
  if (state.phonePollInterval) clearInterval(state.phonePollInterval);
  if (state.activePhoneSession) {
    await fetch(`/phone_upload/${state.activePhoneSession.token}/finish`, { method: "POST" });
  }
  closeModal("modal-phone-qr");
  await loadStagedPhotos();
  navigatePage("photos");
}

// ------------------ 5. ATTENDANCE EXECUTION & REVIEW ------------------

async function setupAttendancePage() {
  const now = new Date();
  document.getElementById("session-date").value = now.toISOString().split("T")[0];
  document.getElementById("session-time").value = now.toTimeString().slice(0, 5);
  updateThresholdHint();
}

async function updateThresholdHint() {
  const auto = document.getElementById("check-auto-threshold").checked;
  const slider = document.getElementById("threshold-slider");
  const hint = document.getElementById("threshold-hint-lbl");

  if (auto) {
    if (state.activeClassId) {
      try {
        const res = await fetch(`/api/attendance/config/${state.activeClassId}`);
        if (res.ok) {
          const data = await res.json();
          slider.value = data.t_accept;
          hint.textContent = `Suggested threshold ${data.t_accept.toFixed(2)} — ${data.basis}`;
          return;
        }
      } catch (e) {}
    }
    hint.textContent = `Automatic threshold ${slider.value}`;
  } else {
    hint.textContent = `Manual threshold ${slider.value} (lower = stricter)`;
  }
}

async function handleRunAttendance() {
  if (!state.activeClassId) return alert("Select a class first.");
  if (state.stagedPhotos.length === 0) return alert("Add at least one group photo in Group Photos first.");

  const btn = document.getElementById("btn-run-attendance");
  const logBox = document.getElementById("attendance-log-box");
  const stageLbl = document.getElementById("attendance-stage-lbl");
  const previewImg = document.getElementById("attendance-preview-img");
  const previewPl = document.getElementById("attendance-preview-placeholder");

  btn.disabled = true;
  btn.textContent = "Analyzing photos...";
  stageLbl.textContent = "Detecting faces and computing embeddings...";
  logBox.textContent = "Starting AI face recognition pipeline...\nLoaded classroom photo evidence.\nRunning neural detector...\n";

  try {
    const form = new FormData();
    form.append("class_id", state.activeClassId);
    form.append("mode", document.getElementById("session-accuracy-mode").value);
    if (!document.getElementById("check-auto-threshold").checked) {
      form.append("threshold", document.getElementById("threshold-slider").value);
    }
    form.append("enhance", "true");

    const res = await fetch("/api/attendance/run", { method: "POST", body: form });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Recognition pipeline error");
    }

    const data = await res.json();
    state.recognitionResult = data;

    logBox.textContent += `Face detection completed in ${data.seconds.toFixed(2)}s.\n` +
      `Detected ${data.summary.faces_detected} faces across classroom photos.\n` +
      `Matched ${data.summary.present} present, ${data.summary.absent} absent, ${data.summary.uncertain} to check.\n` +
      `Opening review dialog...\n`;

    stageLbl.textContent = `Complete: ${data.summary.present} Present, ${data.summary.absent} Absent`;
    previewImg.src = data.boxed_image;
    previewImg.style.display = "block";
    previewPl.style.display = "none";

    openAttendanceReviewDialog(data);
  } catch (err) {
    alert("Attendance run failed: " + err.message);
    logBox.textContent += `ERROR: ${err.message}\n`;
    stageLbl.textContent = "Error during processing";
  } finally {
    btn.disabled = false;
    btn.textContent = "▶ Run Attendance";
  }
}

function openAttendanceReviewDialog(data) {
  const modalBody = document.getElementById("review-modal-body");
  document.getElementById("review-modal-summary").textContent =
    `Review: ${data.summary.present} Present | ${data.summary.absent} Absent | ${data.summary.uncertain} to check`;

  modalBody.innerHTML = "";

  // Uncertain Section
  const uncertains = data.students.filter(s => s.uncertain);
  if (uncertains.length > 0) {
    const uHeader = document.createElement("div");
    uHeader.innerHTML = `<h3 style="color: var(--amber); font-size: 14px; margin-bottom: 8px;">⚠ Need Review — System is not fully certain</h3>`;
    modalBody.appendChild(uHeader);

    uncertains.forEach(s => {
      const card = createReviewStudentCard(s, true);
      modalBody.appendChild(card);
    });
  }

  // Absent Section
  const absents = data.students.filter(s => s.status === "A" && !s.uncertain);
  const aHeader = document.createElement("div");
  aHeader.innerHTML = `<h3 style="font-size: 14px; margin: 16px 0 8px;">Absent Students (${absents.length}) — Confirm or toggle status</h3>`;
  modalBody.appendChild(aHeader);

  absents.forEach(s => {
    const card = createReviewStudentCard(s, false);
    modalBody.appendChild(card);
  });

  // Present Section
  const presents = data.students.filter(s => s.status === "P" && !s.uncertain);
  const pHeader = document.createElement("div");
  pHeader.innerHTML = `<h3 style="color: var(--green); font-size: 14px; margin: 16px 0 8px;">Confident Present (${presents.length})</h3>`;
  modalBody.appendChild(pHeader);

  presents.forEach(s => {
    const card = createReviewStudentCard(s, false);
    modalBody.appendChild(card);
  });

  openModal("modal-attendance-review");
}

function createReviewStudentCard(student, isUncertain) {
  const card = document.createElement("div");
  card.style = `
    display: flex; justify-content: space-between; align-items: center;
    padding: 8px 12px; margin-bottom: 6px; border-radius: var(--radius-sm);
    border: 1px solid ${isUncertain ? "var(--amber)" : "var(--border)"};
    background: ${isUncertain ? "var(--amber-lt)" : "var(--white)"};
  `;

  card.innerHTML = `
    <div>
      <strong>${student.name}</strong> (${student.code})
      <span style="font-size: 11px; color: var(--grey); margin-left: 8px;">Match: ${student.confidence}%</span>
    </div>
    <div style="display: flex; gap: 4px;">
      <button class="btn btn-sm ${student.status === "P" ? "btn-success" : "btn-secondary"}" onclick="setReviewStatus(${student.student_id}, 'P', this)">Present</button>
      <button class="btn btn-sm ${student.status === "A" ? "btn-danger" : "btn-secondary"}" onclick="setReviewStatus(${student.student_id}, 'A', this)">Absent</button>
      <button class="btn btn-sm ${student.status === "L" ? "btn-warning" : "btn-secondary"}" onclick="setReviewStatus(${student.student_id}, 'L', this)">Late</button>
      <button class="btn btn-sm ${student.status === "E" ? "btn-primary" : "btn-secondary"}" onclick="setReviewStatus(${student.student_id}, 'E', this)">Excused</button>
    </div>
  `;
  return card;
}

function setReviewStatus(studentId, newStatus, btn) {
  const student = state.recognitionResult.students.find(s => s.student_id === studentId);
  if (student) {
    student.status = newStatus;
  }
  const parent = btn.parentElement;
  parent.querySelectorAll("button").forEach(b => {
    b.className = "btn btn-sm btn-secondary";
  });
  if (newStatus === "P") btn.className = "btn btn-sm btn-success";
  if (newStatus === "A") btn.className = "btn btn-sm btn-danger";
  if (newStatus === "L") btn.className = "btn btn-sm btn-warning";
  if (newStatus === "E") btn.className = "btn btn-sm btn-primary";
}

async function handleSaveFinalAttendance() {
  if (!state.recognitionResult) return;
  const payload = {
    class_id: state.activeClassId,
    date: document.getElementById("session-date").value,
    time: document.getElementById("session-time").value,
    subject: document.getElementById("session-subject").value || "General",
    faculty: document.getElementById("session-faculty").value || state.user,
    period: document.getElementById("session-period").value || "1",
    mode: document.getElementById("session-accuracy-mode").value,
    records: state.recognitionResult.students.map(s => ({
      student_id: s.student_id,
      status: s.status,
    })),
  };

  try {
    const res = await fetch("/api/attendance/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error("Could not save session");
    const data = await res.json();
    alert("Attendance successfully saved to database!");
    closeModal("modal-attendance-review");
    navigatePage("reports");
  } catch (err) {
    alert("Save error: " + err.message);
  }
}

// ------------------ 6. REPORTS & EDITING ------------------

async function loadReportsList() {
  if (!state.activeClassId) return;
  try {
    const res = await fetch(`/api/reports/sessions?class_id=${state.activeClassId}`);
    if (res.ok) {
      const sessions = await res.json();
      const tbody = document.getElementById("reports-sessions-tbody");
      tbody.innerHTML = "";
      if (sessions.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--grey);">No sessions recorded yet.</td></tr>`;
        return;
      }
      sessions.forEach(s => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><strong>${s.date}</strong></td>
          <td>${s.time}</td>
          <td>${s.subject || "-"}</td>
          <td>${s.period || "1"}</td>
          <td>${s.faculty || "-"}</td>
          <td>
            <span class="badge ${s.pct >= 75 ? "badge-present" : "badge-absent"}">
              ${s.present} / ${s.total} (${s.pct}%)
            </span>
          </td>
          <td>
            <button class="btn btn-secondary btn-sm" onclick="inspectSession(${s.id})">Inspect</button>
          </td>
        `;
        tbody.appendChild(tr);
      });
    }
  } catch (err) {
    console.error("Reports load error:", err);
  }
}

async function inspectSession(sid) {
  try {
    const res = await fetch(`/api/reports/session/${sid}`);
    if (!res.ok) throw new Error("Could not load session detail");
    const data = await res.json();
    let summaryText = `Session on ${data.session.date} (${data.session.subject}):\n\n`;
    data.records.forEach(r => {
      summaryText += `${r.name || r.code}: ${r.status} (dist: ${r.dist ? r.dist.toFixed(2) : "-"})\n`;
    });
    alert(summaryText);
  } catch (err) {
    alert("Inspection error: " + err.message);
  }
}

// ------------------ 7. EMAIL CENTER ------------------

async function loadEmailCenter() {
  if (!state.activeClassId) return;
  const now = new Date();
  const firstDay = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().split("T")[0];
  const lastDay = now.toISOString().split("T")[0];

  document.getElementById("email-from-date").value = firstDay;
  document.getElementById("email-to-date").value = lastDay;

  try {
    const res = await fetch(`/api/email/recipients?class_id=${state.activeClassId}`);
    if (res.ok) {
      const students = await res.json();
      const tbody = document.getElementById("email-recipients-tbody");
      tbody.innerHTML = "";
      students.forEach(s => {
        const emails = s.recipients.map(r => r.email).join(", ") || "(No email registered)";
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><input type="checkbox" class="email-select-checkbox" data-student-id="${s.student_id}"></td>
          <td><strong>${s.code}</strong></td>
          <td>${s.name}</td>
          <td>${emails}</td>
          <td>
            <button class="btn btn-secondary btn-sm" onclick="promptAddEmail(${s.student_id})">+ Add Email</button>
          </td>
        `;
        tbody.appendChild(tr);
      });
    }

    const dRes = await fetch("/api/email/deliveries");
    if (dRes.ok) {
      const history = await dRes.json();
      const hbody = document.getElementById("email-history-tbody");
      hbody.innerHTML = "";
      if (history.length === 0) {
        hbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--grey);">No deliveries sent yet.</td></tr>`;
      } else {
        history.forEach(d => {
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td>${d.recipient}</td>
            <td>${d.student_name} (${d.student_code})</td>
            <td>${d.kind}</td>
            <td><span class="badge ${d.status === "sent" ? "badge-present" : "badge-absent"}">${d.status}</span></td>
            <td>${new Date(d.updated_at * 1000).toLocaleString()}</td>
            <td>
              ${d.status === "failed" ? `<button class="btn btn-secondary btn-sm" onclick="retryDelivery(${d.id})">Retry</button>` : "-"}
            </td>
          `;
          hbody.appendChild(tr);
        });
      }
    }
  } catch (err) {
    console.error("Email center load error:", err);
  }
}

async function promptAddEmail(studentId) {
  const email = prompt("Enter student or parent email address:");
  if (!email || !email.includes("@")) return;
  try {
    await fetch("/api/email/recipients", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ student_id: studentId, email: email.trim(), label: "Primary" }),
    });
    await loadEmailCenter();
  } catch (err) {
    alert("Could not save email: " + err);
  }
}

async function handlePreviewEmail() {
  const selected = getSelectedEmailStudentIds();
  if (selected.length === 0) return alert("Select at least one student to preview.");

  const sid = selected[0];
  const fromDate = document.getElementById("email-from-date").value;
  const toDate = document.getElementById("email-to-date").value;

  try {
    const res = await fetch("/api/email/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        student_id: sid,
        class_id: state.activeClassId,
        report_from: fromDate,
        report_to: toDate,
      }),
    });
    if (!res.ok) throw new Error("Could not generate email preview");
    const data = await res.json();

    document.getElementById("email-preview-subject").textContent = "Subject: " + data.subject;
    document.getElementById("email-preview-body").textContent = data.text_body;
    openModal("modal-email-preview");
  } catch (err) {
    alert("Preview error: " + err.message);
  }
}

async function handleSendEmail() {
  const selected = getSelectedEmailStudentIds();
  if (selected.length === 0) return alert("Select student(s) to send reports to.");

  if (!confirm(`Queue personalized attendance reports for ${selected.length} student(s)?`)) return;

  const fromDate = document.getElementById("email-from-date").value;
  const toDate = document.getElementById("email-to-date").value;

  try {
    const res = await fetch("/api/email/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        student_ids: selected,
        class_id: state.activeClassId,
        report_from: fromDate,
        report_to: toDate,
      }),
    });
    const data = await res.json();
    alert(data.message || "Emails queued successfully.");
    await loadEmailCenter();
  } catch (err) {
    alert("Send error: " + err);
  }
}

function getSelectedEmailStudentIds() {
  const boxes = document.querySelectorAll(".email-select-checkbox:checked");
  return Array.from(boxes).map(b => parseInt(b.dataset.studentId));
}

async function retryDelivery(did) {
  try {
    await fetch(`/api/email/retry/${did}`, { method: "POST" });
    await loadEmailCenter();
  } catch (err) {
    alert("Retry failed: " + err);
  }
}

// ------------------ 8. RECOVERY & LOCAL ASSISTANT ------------------

async function handleCalculateRecovery() {
  const attended = parseInt(document.getElementById("recovery-attended").value) || 0;
  const absent = parseInt(document.getElementById("recovery-absent").value) || 0;
  const target = parseFloat(document.getElementById("recovery-target").value) || 75.0;

  try {
    const res = await fetch("/api/recovery/calculate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ attended, absent, target }),
    });
    if (!res.ok) throw new Error("Calculation failed");
    const data = await res.json();
    const plan = data.plan;

    const box = document.getElementById("recovery-results-box");
    box.innerHTML = `
      <div><strong>Current Attendance:</strong> ${plan.current !== null ? plan.current.toFixed(1) + "%" : "No classes"} (${plan.attended} attended, ${plan.absent} absent)</div>
      <div><strong>Target Goal:</strong> ${plan.target}%</div>
      <div style="margin-top: 8px;">
        ${plan.classes_needed !== null
          ? `<span class="badge ${plan.classes_needed > 0 ? "badge-uncertain" : "badge-present"}">Classes needed: ${plan.classes_needed}</span>`
          : ""}
        ${plan.safe_to_miss !== null
          ? `<span class="badge badge-present" style="margin-left: 6px;">Safe to miss: ${plan.safe_to_miss}</span>`
          : ""}
      </div>
    `;
  } catch (err) {
    alert("Calculation error: " + err.message);
  }
}

async function handleAskAssistant() {
  const qInput = document.getElementById("assistant-question-input");
  const aBox = document.getElementById("assistant-answer-box");
  const question = qInput.value.trim();
  if (!question) return;

  aBox.textContent = "Consulting local Upasthiti assistant...";
  try {
    const res = await fetch("/api/assistant/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, class_id: state.activeClassId }),
    });
    const data = await res.json();
    aBox.textContent = data.answer;
  } catch (err) {
    aBox.textContent = "Assistant is currently offline.";
  }
}

// ------------------ 9. REVIEW REQUESTS ------------------

async function loadReviewRequestsQueue() {
  try {
    const res = await fetch("/api/review_requests");
    if (res.ok) {
      const requests = await res.json();
      const tbody = document.getElementById("reviews-queue-tbody");
      tbody.innerHTML = "";
      if (requests.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--grey);">No review requests pending.</td></tr>`;
        return;
      }
      requests.forEach(r => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>#${r.id}</td>
          <td><strong>${r.student_code || r.student_id}</strong></td>
          <td>${r.date}</td>
          <td>${r.subject || "-"}</td>
          <td><span class="badge badge-absent">${r.original_status}</span></td>
          <td>${r.reason}</td>
          <td><span class="badge badge-uncertain">${r.status}</span></td>
          <td>
            <button class="btn btn-success btn-sm" onclick="transitionReview(${r.id}, 'change', 'P')">Approve Present</button>
            <button class="btn btn-secondary btn-sm" onclick="transitionReview(${r.id}, 'keep')">Keep</button>
            <button class="btn btn-danger-lt btn-sm" onclick="transitionReview(${r.id}, 'dismiss')">Dismiss</button>
          </td>
        `;
        tbody.appendChild(tr);
      });
    }
  } catch (err) {
    console.error("Review requests load error:", err);
  }
}

async function transitionReview(reqId, action, newStatus = null) {
  try {
    await fetch(`/api/review_requests/${reqId}/transition`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, new_status: newStatus, reason: "Resolved via Web Review" }),
    });
    await loadReviewRequestsQueue();
  } catch (err) {
    alert("Transition failed: " + err);
  }
}

// ------------------ 10. STUDENT PORTAL ------------------

async function loadStudentPortalData() {
  try {
    const sRes = await fetch("/api/student/portal/summary");
    if (sRes.ok) {
      const data = await sRes.json();
      document.getElementById("student-portal-greeting").textContent = `Welcome, ${data.student.name}`;
      document.getElementById("student-portal-sub").textContent = `Student ID: ${data.student.code}`;
      const pct = data.overall.current !== null ? data.overall.current.toFixed(1) + "%" : "0%";
      document.getElementById("student-portal-pct").textContent = pct;

      const guideBox = document.getElementById("student-portal-guidance");
      guideBox.innerHTML = `
        <div><strong>Overall Attendance:</strong> ${pct} (${data.overall.attended} attended, ${data.overall.absent} absent)</div>
        <div><strong>Target Goal:</strong> ${data.overall.target}%</div>
        <div style="margin-top: 8px;">
          ${data.overall.classes_needed !== null ? `<div>• Attend the next <strong>${data.overall.classes_needed}</strong> classes to reach your target.</div>` : ""}
          ${data.overall.safe_to_miss !== null ? `<div>• You can safely miss <strong>${data.overall.safe_to_miss}</strong> more classes.</div>` : ""}
        </div>
      `;

      // Subjects table
      const subTbody = document.getElementById("student-portal-subjects-tbody");
      subTbody.innerHTML = "";
      data.subjects.forEach(sub => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><strong>${sub.subject}</strong></td>
          <td>${sub.attended}</td>
          <td>${sub.absent}</td>
          <td>${sub.current !== null ? sub.current.toFixed(1) + "%" : "-"}</td>
        `;
        subTbody.appendChild(tr);
      });
    }

    // Attendance History
    const hRes = await fetch("/api/student/portal/history");
    if (hRes.ok) {
      const records = await hRes.json();
      const hbody = document.getElementById("student-portal-history-tbody");
      hbody.innerHTML = "";
      records.forEach(r => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${r.date}</td>
          <td>${r.time}</td>
          <td>${r.subject || "General"}</td>
          <td><span class="badge ${r.status === "P" ? "badge-present" : "badge-absent"}">${r.status}</span></td>
          <td>
            ${r.status === "A" ? `<button class="btn btn-secondary btn-sm" onclick="openSubmitReviewModal(${r.session_id})">Report Discrepancy</button>` : "-"}
          </td>
        `;
        hbody.appendChild(tr);
      });
    }
  } catch (err) {
    console.error("Student portal load error:", err);
  }
}

function openSubmitReviewModal(sessionId) {
  document.getElementById("review-session-id").value = sessionId;
  openModal("modal-submit-review");
}

async function handleSubmitReviewClaim() {
  const sessionId = parseInt(document.getElementById("review-session-id").value);
  const reason = document.getElementById("review-reason-select").value;
  const explanation = document.getElementById("review-explanation-text").value.trim();

  try {
    const res = await fetch("/api/review_requests/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, reason, explanation }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Could not submit review claim");
    }
    alert("Review claim submitted. Faculty will be notified.");
    closeModal("modal-submit-review");
    await loadStudentPortalData();
  } catch (err) {
    alert("Submission error: " + err.message);
  }
}

// ------------------ 11. SETTINGS & CLASSES ------------------

async function handleCreateClass() {
  const name = document.getElementById("new-class-name").value.trim();
  if (!name) return alert("Enter class name.");
  try {
    const res = await fetch("/api/classes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (!res.ok) throw new Error("Could not create class");
    closeModal("modal-new-class");
    document.getElementById("new-class-name").value = "";
    await loadClasses();
  } catch (err) {
    alert("Class creation failed: " + err);
  }
}

async function handleSaveSettings() {
  const payload = {
    limit_warn: parseInt(document.getElementById("setting-warn").value),
    limit_critical: parseInt(document.getElementById("setting-critical").value),
    default_mode: document.getElementById("setting-default-mode").value,
    sender_email: document.getElementById("setting-sender-email").value,
    smtp_host: document.getElementById("setting-smtp-host").value,
    smtp_port: parseInt(document.getElementById("setting-smtp-port").value),
    smtp_user: document.getElementById("setting-smtp-user").value,
    smtp_password: document.getElementById("setting-smtp-pw").value,
  };

  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      alert("Settings saved successfully.");
    }
  } catch (err) {
    alert("Save settings error: " + err);
  }
}

async function handleCreateBackup() {
  try {
    const res = await fetch("/api/backup/create", { method: "POST" });
    const data = await res.json();
    alert("Verified backup created:\n" + data.backup_path);
  } catch (err) {
    alert("Backup error: " + err);
  }
}

// ------------------ MODAL UTILITIES ------------------

function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = "flex";
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = "none";
}
