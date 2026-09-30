// Upasthiti Web Dashboard Client Logic
document.addEventListener('DOMContentLoaded', () => {
    // Navigation Tabs
    const tabBtns = document.querySelectorAll('.nav-tab-btn');
    const tabSections = document.querySelectorAll('.tab-section');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-tab');
            tabBtns.forEach(b => b.classList.remove('active'));
            tabSections.forEach(s => s.classList.remove('active'));
            btn.classList.add('active');
            const targetSection = document.getElementById(targetId);
            if (targetSection) targetSection.classList.add('active');

            if (targetId === 'tab-classes') loadClasses();
            if (targetId === 'tab-reports') loadReports();
        });
    });

    // Global State
    let currentStream = null;
    let currentAttendanceData = null;
    let selectedImageFile = null;

    // Elements
    const classSelect = document.getElementById('class-select');
    const photoFileInput = document.getElementById('photo-file-input');
    const videoElem = document.getElementById('webcam-video');
    const canvasElem = document.getElementById('capture-canvas');
    const startCameraBtn = document.getElementById('start-camera-btn');
    const snapBtn = document.getElementById('snap-btn');
    const processBtn = document.getElementById('process-btn');
    const resultsContainer = document.getElementById('results-container');
    const boxedImageElem = document.getElementById('boxed-result-image');
    const attendanceTableBody = document.getElementById('attendance-table-body');
    const saveSessionBtn = document.getElementById('save-session-btn');
    const processSpinner = document.getElementById('process-spinner');

    // Load initial system stats & classes
    fetchStatus();
    loadClasses();

    function fetchStatus() {
        fetch('/api/status')
            .then(res => res.json())
            .then(data => {
                const statElem = document.getElementById('system-status-text');
                if (statElem) {
                    statElem.textContent = data.models_ready ? 'AI Models Active' : 'Waiting for Models';
                }
            })
            .catch(console.error);
    }

    // Load Class Options
    function loadClasses() {
        fetch('/api/classes')
            .then(res => res.json())
            .then(classes => {
                // Populate attendance class dropdown
                classSelect.innerHTML = '<option value="">-- Choose Class --</option>';
                classes.forEach(c => {
                    const opt = document.createElement('option');
                    opt.value = c.id;
                    opt.textContent = `${c.name} ${c.branch ? '(' + c.branch + ')' : ''}`;
                    classSelect.appendChild(opt);
                });

                // Populate Class management table
                renderClassesList(classes);
            })
            .catch(console.error);
    }

    // Camera Controls
    startCameraBtn.addEventListener('click', async () => {
        if (currentStream) {
            // Stop camera
            currentStream.getTracks().forEach(track => track.stop());
            currentStream = null;
            videoElem.style.display = 'none';
            snapBtn.style.display = 'none';
            startCameraBtn.innerHTML = '📷 Open Camera';
            return;
        }

        try {
            currentStream = await navigator.mediaDevices.getUserMedia({
                video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'environment' }
            });
            videoElem.srcObject = currentStream;
            videoElem.style.display = 'block';
            snapBtn.style.display = 'inline-flex';
            startCameraBtn.innerHTML = '⏹ Stop Camera';
            document.getElementById('upload-placeholder').style.display = 'none';
        } catch (err) {
            alert('Could not access camera: ' + err.message);
        }
    });

    // Snap photo from webcam
    snapBtn.addEventListener('click', () => {
        if (!currentStream) return;
        canvasElem.width = videoElem.videoWidth;
        canvasElem.height = videoElem.videoHeight;
        const ctx = canvasElem.getContext('2d');
        ctx.drawImage(videoElem, 0, 0, canvasElem.width, canvasElem.height);
        
        // Stop camera stream after snapping
        currentStream.getTracks().forEach(track => track.stop());
        currentStream = null;
        videoElem.style.display = 'none';
        snapBtn.style.display = 'none';
        startCameraBtn.innerHTML = '📷 Open Camera';

        // Display captured canvas as preview
        const dataUrl = canvasElem.toDataURL('image/jpeg', 0.95);
        document.getElementById('preview-image').src = dataUrl;
        document.getElementById('preview-image').style.display = 'block';
        document.getElementById('upload-placeholder').style.display = 'none';
        selectedImageFile = null; // Using canvas
    });

    // File input selection
    photoFileInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) {
            selectedImageFile = file;
            const reader = new FileReader();
            reader.onload = (evt) => {
                document.getElementById('preview-image').src = evt.target.result;
                document.getElementById('preview-image').style.display = 'block';
                document.getElementById('upload-placeholder').style.display = 'none';
                if (videoElem) videoElem.style.display = 'none';
            };
            reader.readAsDataURL(file);
        }
    });

    // Process Attendance
    processBtn.addEventListener('click', async () => {
        const classId = classSelect.value;
        if (!classId) {
            alert('Please select a class first.');
            return;
        }

        const formData = new FormData();
        formData.append('class_id', classId);
        formData.append('mode', document.getElementById('accuracy-mode').value);

        if (selectedImageFile) {
            formData.append('image', selectedImageFile);
        } else {
            const previewImg = document.getElementById('preview-image');
            if (previewImg.src && previewImg.src.startsWith('data:image')) {
                formData.append('image_base64', previewImg.src);
            } else {
                alert('Please upload a photo or capture one with the camera first.');
                return;
            }
        }

        // Show spinner
        processSpinner.style.display = 'inline-block';
        processBtn.disabled = true;

        try {
            const res = await fetch('/api/attendance/recognize', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.detail || 'Attendance recognition failed.');
            }

            renderRecognitionResults(data);
        } catch (err) {
            alert('Error: ' + err.message);
        } finally {
            processSpinner.style.display = 'none';
            processBtn.disabled = false;
        }
    });

    // Render Results
    function renderRecognitionResults(data) {
        currentAttendanceData = data;
        resultsContainer.style.display = 'block';
        resultsContainer.scrollIntoView({ behavior: 'smooth' });

        // Show annotated image
        boxedImageElem.src = data.boxed_image;

        // Update stats
        document.getElementById('stat-detected').textContent = data.summary.faces_detected;
        document.getElementById('stat-present').textContent = data.summary.present;
        document.getElementById('stat-absent').textContent = data.summary.absent;

        // Render roster table
        attendanceTableBody.innerHTML = '';
        data.students.forEach((student, index) => {
            const tr = document.createElement('tr');
            tr.className = 'attendance-row';
            tr.innerHTML = `
                <td><strong>${student.code}</strong></td>
                <td>${student.name || '—'}</td>
                <td>
                    <button class="toggle-status-btn ${student.status === 'P' ? 'present' : 'absent'}" data-index="${index}">
                        ${student.status === 'P' ? '✓ PRESENT' : '✗ ABSENT'}
                    </button>
                </td>
                <td><small style="color: var(--text-dim);">${student.confidence}%</small></td>
            `;
            attendanceTableBody.appendChild(tr);
        });

        // Add toggle listeners
        document.querySelectorAll('.toggle-status-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const idx = parseInt(btn.getAttribute('data-index'));
                const st = currentAttendanceData.students[idx];
                st.status = (st.status === 'P') ? 'A' : 'P';
                btn.className = `toggle-status-btn ${st.status === 'P' ? 'present' : 'absent'}`;
                btn.textContent = (st.status === 'P') ? '✓ PRESENT' : '✗ ABSENT';

                // Recount summary
                const presentCount = currentAttendanceData.students.filter(s => s.status === 'P').length;
                document.getElementById('stat-present').textContent = presentCount;
                document.getElementById('stat-absent').textContent = currentAttendanceData.students.length - presentCount;
            });
        });
    }

    // Save Attendance Session
    saveSessionBtn.addEventListener('click', async () => {
        if (!currentAttendanceData) return;

        const classId = parseInt(classSelect.value);
        const payload = {
            class_id: classId,
            date: new Date().toISOString().split('T')[0],
            time: new Date().toTimeString().slice(0, 5),
            subject: document.getElementById('session-subject').value || 'Lecture',
            faculty: document.getElementById('session-faculty').value || 'Faculty',
            period: document.getElementById('session-period').value || '1',
            mode: document.getElementById('accuracy-mode').value,
            records: currentAttendanceData.students.map(s => ({
                student_id: s.student_id,
                status: s.status
            }))
        };

        saveSessionBtn.disabled = true;
        saveSessionBtn.textContent = 'Saving...';

        try {
            const res = await fetch('/api/attendance/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (res.ok) {
                alert('Attendance successfully recorded and saved to database!');
                resultsContainer.style.display = 'none';
            } else {
                alert('Save failed: ' + (data.detail || 'Unknown error'));
            }
        } catch (err) {
            alert('Save error: ' + err.message);
        } finally {
            saveSessionBtn.disabled = false;
            saveSessionBtn.innerHTML = '💾 Confirm & Save to Database';
        }
    });

    // ---------------- Class Management ----------------
    function renderClassesList(classes) {
        const listElem = document.getElementById('classes-list');
        if (!listElem) return;
        listElem.innerHTML = '';
        classes.forEach(c => {
            const card = document.createElement('div');
            card.className = 'glass-card';
            card.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem;">
                    <h3 style="font-size:1.15rem; font-weight:700;">${c.name}</h3>
                    <span class="brand-tag">${c.branch || 'Class'}</span>
                </div>
                <p style="font-size:0.88rem; color:var(--text-muted); margin-bottom:1rem;">
                    College: ${c.college || '—'}<br>
                    Year / Section: ${c.year || '—'} / ${c.section || '—'}
                </p>
                <button class="btn btn-outline view-roster-btn" data-id="${c.id}" data-name="${c.name}" style="width:100%;">
                    👥 Manage Roster
                </button>
            `;
            listElem.appendChild(card);
        });

        document.querySelectorAll('.view-roster-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const cid = btn.getAttribute('data-id');
                const cname = btn.getAttribute('data-name');
                openClassRoster(cid, cname);
            });
        });
    }

    // Add Class Form
    const createClassForm = document.getElementById('create-class-form');
    if (createClassForm) {
        createClassForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const payload = {
                name: document.getElementById('new-class-name').value,
                college: document.getElementById('new-class-college').value,
                year: document.getElementById('new-class-year').value,
                branch: document.getElementById('new-class-branch').value,
                section: document.getElementById('new-class-section').value
            };

            const res = await fetch('/api/classes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (res.ok) {
                alert('Class added successfully!');
                createClassForm.reset();
                loadClasses();
            } else {
                const err = await res.json();
                alert('Error: ' + err.detail);
            }
        });
    }

    // Open Roster
    function openClassRoster(classId, className) {
        document.getElementById('roster-modal').style.display = 'block';
        document.getElementById('roster-class-name').textContent = className;
        document.getElementById('roster-class-id').value = classId;
        loadRosterStudents(classId);
    }

    function loadRosterStudents(classId) {
        fetch(`/api/classes/${classId}/students`)
            .then(res => res.json())
            .then(students => {
                const tbody = document.getElementById('roster-table-body');
                tbody.innerHTML = '';
                students.forEach(s => {
                    const tr = document.createElement('tr');
                    tr.className = 'attendance-row';
                    tr.innerHTML = `
                        <td><strong>${s.code}</strong></td>
                        <td>${s.name}</td>
                        <td><span class="brand-tag">${s.enrolled_faces} photos</span></td>
                        <td>
                            <label class="btn btn-outline" style="padding:0.3rem 0.7rem; font-size:0.8rem; cursor:pointer;">
                                ➕ Add Photo
                                <input type="file" accept="image/*" style="display:none;" onchange="uploadStudentPhoto(${classId}, '${s.code}', this)">
                            </label>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
            });
    }

    window.uploadStudentPhoto = async function(classId, code, input) {
        const file = input.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);

        const res = await fetch(`/api/classes/${classId}/students/${code}/enroll`, {
            method: 'POST',
            body: formData
        });

        if (res.ok) {
            alert(`Photo enrolled for ${code}!`);
            loadRosterStudents(classId);
        } else {
            const err = await res.json();
            alert('Enrollment error: ' + (err.detail || 'Could not enroll photo'));
        }
    };

    // Close Modal
    const closeModalBtn = document.getElementById('close-roster-modal');
    if (closeModalBtn) {
        closeModalBtn.addEventListener('click', () => {
            document.getElementById('roster-modal').style.display = 'none';
        });
    }

    // Add Student Form
    const addStudentForm = document.getElementById('add-student-form');
    if (addStudentForm) {
        addStudentForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const classId = document.getElementById('roster-class-id').value;
            const payload = {
                code: document.getElementById('new-student-code').value,
                name: document.getElementById('new-student-name').value
            };

            const res = await fetch(`/api/classes/${classId}/students`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (res.ok) {
                addStudentForm.reset();
                loadRosterStudents(classId);
            } else {
                const err = await res.json();
                alert('Error adding student: ' + err.detail);
            }
        });
    }

    // ---------------- Reports ----------------
    function loadReports() {
        fetch('/api/reports/recent')
            .then(res => res.json())
            .then(sessions => {
                const tbody = document.getElementById('reports-table-body');
                tbody.innerHTML = '';
                if (!sessions || sessions.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:2rem; color:var(--text-dim);">No attendance sessions recorded yet.</td></tr>';
                    return;
                }
                sessions.forEach(s => {
                    const tr = document.createElement('tr');
                    tr.className = 'attendance-row';
                    tr.innerHTML = `
                        <td><strong>${s.date}</strong></td>
                        <td>${s.time || '—'}</td>
                        <td>${s.class_name || 'Class'}</td>
                        <td>${s.subject || 'General'}</td>
                        <td>${s.faculty || 'Admin'}</td>
                        <td><span class="stat-badge badge-present">Recorded</span></td>
                    `;
                    tbody.appendChild(tr);
                });
            })
            .catch(console.error);
    }
});
