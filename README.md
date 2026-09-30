# Upasthiti

> Offline-first Face-Recognition Classroom Attendance System

Upasthiti is a Windows desktop application for managing classroom attendance using face recognition models (InsightFace & DeepFace). It features student enrollment, automated group photo attendance, quality diagnostics, reports, and administrative audit trails.

## Features

- **Automated Face Recognition**: Dual-engine support with InsightFace (antelopev2 / buffalo_l) and DeepFace (ArcFace / VGG-Face).
- **Fast Enrollment**: Bulk photo import with automatic facial grouping, CSV metadata import, and mobile local Wi-Fi upload.
- **Group Photo Processing**: Classroom photo processing with automated image quality checks (blur, illumination, resolution, duplicate detection).
- **Interactive Review Queue**: Point-in-photo facial tagging, quick keyboard shortcuts (`Up`/`Down`, `Space`, `Enter`), and uncertainty flags.
- **Reporting & Analytics**: Interactive calendar attendance heatmaps, session details with boxed detection photos, and exports in Excel/Word formats.
- **Security & Privacy**: Offline-first architecture, local SQLite database with DPAPI credential encryption, and zero cloud dependency.

## Getting Started

### Prerequisites
- Windows 10 or 11 (64-bit)
- Python 3.10, 3.11, or 3.12 (with "Add Python to PATH" enabled)

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/nagalingeshwara1963-design/Upasthiti.git
   cd Upasthiti
   ```
2. Run setup:
   - Double-click `Setup_Upasthiti.bat` to create the virtual environment, install requirements, and download required recognition models.
### Launching Options

- **Desktop Edition**: Double-click `Start_Upasthiti.bat` (native Windows GUI)
- **Web Edition**: Double-click `Start_Web_Upasthiti.bat` (opens modern browser interface at `http://localhost:8000`)
- **Cloud Deployment**: See [README_DEPLOY_WEB.md](README_DEPLOY_WEB.md) for 1-click free deployment to Render.com or Hugging Face Spaces.

## Architecture

- `app/web/`: FastAPI web server, REST endpoints, and modern web interface
- `app/launch.py`: Desktop startup harness and error reporter

- `app/launch.py`: Startup harness and error reporter
- `app/ui/`: CustomTkinter user interface components
- `app/engine/`: Face detection, embedding extraction, and matching pipelines
- `app/services.py`: Application business logic and engine-UI bridge
- `app/db.py`: SQLite persistence and migrations
- `app/reports.py` & `app/exports.py`: Attendance reporting and document generation
