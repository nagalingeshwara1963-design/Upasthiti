UPASTHITI - Face-recognition classroom attendance
==================================================

INSTALL (fresh folder - keep this separate from any older attendance code)
1. Unzip this so that C:\Upasthiti\Setup_Upasthiti.bat exists (or wherever you keep it -
   just remember the folder).
2. Install Python 3.10, 3.11 or 3.12 from python.org - tick "Add Python to PATH" during
   install.
3. Double-click Setup_Upasthiti.bat. It creates a virtual environment, installs the
   required packages, and downloads about 600 MB of face-recognition models. This step
   needs an internet connection and only has to be done once.
4. Double-click Start_Upasthiti.bat to open the app. First launch asks you to set an
   admin password.

IF SOMETHING GOES WRONG
- Double-click Start_Upasthiti_debug.bat instead - it keeps a black window open showing
  the exact error.
- Every startup error is also saved to data\logs\error.log.

WHAT'S INSIDE
- Enroll          Bulk-import photos (about 4 per student); same-person photos are
                   grouped automatically. Import IDs from a CSV (Student ID, Name) to
                   skip typing them by hand. "Upload from Phone" accepts photos through
                   a temporary QR/local-Wi-Fi session. "Manage Enrolled" lets you add photos, view
                   a student's attendance history, or archive a student. Archiving removes them from
                   active enrollment and matching while preserving attendance, review, and edit history.
- Group Photos    Add classroom photos (browse or webcam), with automatic quality
                   warnings (blur, low light, low resolution, duplicates). "Upload from
                   Phone" adds phone photos to this same photo queue.
- Attendance      Pick faculty/subject/period (typed once, then chosen from a list
                   afterwards), choose an accuracy mode, and run. Live preview with boxes
                   appearing, a progress bar and a log. Afterwards, review anything
                   uncertain - use "Point in Photo" to click a missed student's face
                   directly - confirm absentees, and save.
                     Keyboard shortcuts in the review screen: Up/Down move between
                     students, Enter cycles their status, Space toggles Present/Absent,
                     Esc cancels.
- Reports         A calendar coloured by attendance percentage. Click a date to see its
                   sessions; open any session to view the boxed photos and the
                   attendance list, or download it as Word or Excel. Day and month
                   reports are also available. Faculty can edit a session within
                   30 calendar days from the session date; admin can edit anytime; every
                   edit is logged.
- Home             Today's classes, students below the attendance limit, and recent
                   reports, plus a getting-started checklist on first use.
- Settings         College name and logo, attendance-limit thresholds, group-photo
                   retention, account management (admin/faculty), a database
                   maintenance tool (finds and fixes leftover data), and an audit-log
                   export (every attendance change ever made, as Excel or CSV).
- Models & Licences Choose which recognition model(s) run: two InsightFace models
                   (most accurate, non-commercial research licence) and two DeepFace
                   models (free for commercial use, somewhat less accurate). Mix and
                   match, or use the "Recommended" or "Commercial-safe" one-click combos.
                   Class galleries record recognizer identity/version. Changing models blocks
                   matching until Enroll > Manage Enrolled > Rebuild Recognition Gallery
                   regenerates embeddings from saved enrollment photos.
- Help             A quick-start guide and an expandable FAQ.

ACCOUNTS
- The first time the app runs, you set the admin password.
- Admin can add faculty accounts in Settings. Faculty log in with their own username and
  password and receive access only to classes assigned in Settings. Faculty can edit
  attendance through 30 calendar days after its session date; admins retain the override.
- Students sign in with their exact name and Student ID. At first login, the Student ID is
  a temporary password and must be replaced with a password of at least 10 characters.
  The student portal shows only the authenticated student's own attendance, recovery,
  reports, review requests, notifications, profile, and local deterministic chat.

RECOVERY AND REVIEWS
- Attendance recovery uses the same Present/Late/Absent/Excused/OD counting rule as
  reports. What-if calculations are deterministic scenarios, not forecasts.
- Students may request review within 30 days of class, or within 10 days after a
  successfully sent absence notice or student report covering that date. Requests never
  change attendance automatically. Late requests are escalated for administrator review.

DEMO MODE AND BACKUPS
- Explore Demo Mode from the login screen. It uses a disposable temporary data directory,
  synthetic sample records, no copied biometrics, and a mail service that refuses sends.
  Exiting discards the demo directory.
- Administrators can create a verified local ZIP backup and validate/restore one from
  Settings. It contains the database, enrollment photos, galleries, and saved group-photo
  evidence; protect it as sensitive biometric data. Restore preserves a pre-restore backup.
  Backups do not include model weights or temporary phone uploads. Protected email tokens
  may only work under the same Windows user account.

YOUR DATA
- Everything - students, photos, attendance, settings - lives in the "data" folder next
  to this file. Attendance rows remain after photo evidence cleanup. Admins can manually
  purge boxed group-photo evidence older than the configured retention age; sessions with
  active review requests are retained. The phone-photo option transfers images only over
  your local Wi-Fi, with no cloud relay.

PHONE PHOTO UPLOAD
- Choose "Upload from Phone" in Enroll or Group Photos, connect both devices to the same
  trusted private Wi-Fi, then scan the QR code. The temporary link expires after 15 minutes
  or when the desktop session closes. Upload supports JPEG, PNG, and BMP, with per-photo
  and session limits. The phone offers previews, remove/retake, upload progress, and
  failed-photo retry. Group Photos sessions can show aggregate laptop-side recognition
  feedback while capturing; coverage is a count of unique confident matches, not accuracy.
  Finish opens the existing human-review workflow; attendance is saved only from that review.
- Photos travel directly over local HTTP, without TLS or cloud relay. Do not use a public
  or untrusted network. If the phone cannot connect, check guest Wi-Fi isolation and the
  laptop's private-network firewall permission. Actual device/network combinations vary.

EMAIL MANAGEMENT AND NOTIFICATIONS
- Open Settings > Email as an administrator. Select Gmail, Outlook/Microsoft, or SMTP /
  Other, enter the sender address, then Save. Gmail starts with
  `nagalingeshwara1963@gmail.com` prefilled as an editable default; this does not connect
  or authorize the account. Email is optional; attendance and reports
  continue to work with email disabled. Save changes to add or change the organization
  sender; Disconnect removes the local sender configuration and leaves student recipients
  and attendance history intact. Send a test email to verify provider acceptance.
- Gmail and Microsoft connect using OAuth 2.0. For Gmail, create/select a Google Cloud
  project, enable Gmail API, set the OAuth consent app name to Upasthiti, add the sender
  as a test user if the app is in Testing, then create an OAuth client of type Desktop app.
  Enter its public client ID in Settings > Email. No downloaded JSON credentials file is
  needed. This desktop environment has no `gcloud` CLI, so project/API/client creation was
  not automated. Gmail requests `gmail.send` plus OpenID `openid email` only to verify the
  signed-in account address; it requests no Gmail read, modify, delete, or full-mailbox
  scope. The authorized account must match Sender Email or the token is discarded. See
  Google's [desktop OAuth guide](https://developers.google.com/identity/protocols/oauth2/native-app),
  [Gmail API enablement](https://console.cloud.google.com/apis/library/gmail.googleapis.com),
  and [OpenID token verification](https://developers.google.com/identity/openid-connect/openid-connect).
  Microsoft setup also requires an Entra public-client registration with device-code
  sign-in and delegated Mail.Send permission; enter its tenant ID or "common". Gmail's
  client secret is optional for desktop clients and, if supplied, is protected locally.
  Click Connect Gmail, choose the matching sender account in Google's browser flow, then
  enable Email. The OAuth client ID, sender, and verified identity are stored in the local
  SQLite `settings.email_config` value; the refresh token and optional client secret are
  protected with Windows DPAPI. No credential JSON file is used. OAuth access tokens are kept
  in memory; refresh tokens are protected with Windows DPAPI for the current Windows
  user. A different Windows account cannot decrypt the saved token.
- Gmail can use SMTP with an app password where the Google account allows it. SMTP /
  Other supports custom STARTTLS or SSL/TLS servers and an SMTP credential. Exchange
  Online uses OAuth here; do not enter a Microsoft mailbox password. Providers and
  organizations can restrict SMTP, OAuth consent, app registrations, or API permissions.
  See Google's [Gmail API sending guide](https://developers.google.com/gmail/api/guides/sending), and
  Microsoft's [SMTP AUTH guidance](https://learn.microsoft.com/en-us/exchange/clients-and-mobile-in-exchange-online/authenticated-client-smtp-submission)
  and [OAuth guide](https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth).
- During Enroll > Import New, add zero or multiple labeled email recipients to a student
  before saving. Manage Enrolled > Emails lets administrators add, edit, enable/disable,
  correct, or remove those addresses later. Duplicate addresses for one student are
  rejected. Existing students without email remain valid. Removing a student removes
  recipient rows; minimal saved delivery history remains.
- Automatic absence notices are OFF by default. Turn on both Email enabled and Automatic
  absent-student notices to queue one private message per enabled recipient, only after
  reviewed attendance is saved. Present students are never sent these notices. Low
  attendance is not an automatic email rule. Failed messages appear in Settings > Email
  and can be retried; successful messages are not retried. A provider acceptance is not
  proof that the recipient's inbox received the message.
- Open Email Center and select the class in the application header. Monthly selection
  fills the From/To dates, which remain editable and have calendar pickers; Semester and
  Custom also use editable DD-MM-YYYY dates, with no assumed academic calendar. Search
  students by name or ID and use Send Selected for an explicit selection. Preview a student's actual
  personalized report, then Send to that student's enabled recipients. Send All confirms
  student/address counts and creates separate messages; no student receives a class-wide
  report. Student messages contain only their own counts, subjects and absent dates, and
  never include an enrolled face image. The older Reports > Email Attendance Report
  remains available for selected students or an administrative class workbook; the workbook
  attachment limit is 2 MiB.
- Optional one-shot scheduled student reports can be created, edited (class, dates and
  send date), disabled, or deleted in Email Center. No schedule is created by default.
  The desktop app must be open, the computer on, a sender configured/enabled, and an
  administrator logged in when the due check runs. Upasthiti checks about once a minute;
  if the app was closed on the due date, an overdue schedule is picked up at the next
  eligible check after reopening. It does not run while closed or powered off. Scheduling is separate from
  default-off automatic absence notices. Retry Failed skips successful and permanent
  failures; history's Sent status means provider accepted, not inbox delivery.
- If a send fails, use the failure detail in Settings > Email. Check the test result,
  provider sign-in, OAuth consent/permissions, SMTP host/port/security, and account
  policy. Expired or revoked OAuth access can be reconnected. Never paste an account
  password into a report or a source/config file.
- Manual verification with a real provider (only to a mailbox you control): in an
  isolated test copy, add/connect a sender in Settings > Email and send a test email;
  enroll a test student with a student and parent address; choose that class and a
  Monthly/Custom period in Email Center, inspect Preview, and send one report; correct
  or remove a recipient in Manage Enrolled and confirm the list updates. To test absence,
  enable Automatic absent-student notices and save an explicitly reviewed test session
  where one test student is absent and another present; verify only the absent student's
  recipients receive it, then turn the setting off. To test scheduling, create a future
  date-range schedule and leave Upasthiti open, the computer on, and an administrator
  logged in at the due date. Do not use production attendance records for these checks.

ACCURACY TESTING ON YOUR OWN PHOTOS
  venv\Scripts\python.exe -m app.tools.benchmark my_manifest.json balanced
(manifest format is documented at the top of app\tools\benchmark.py)

LICENCE NOTE
The default (recommended) face models - InsightFace Buffalo_L and AntelopeV2 - are
published for non-commercial research use. If you plan to sell or commercially deploy
Upasthiti, switch to the DeepFace combo in "Models & Licences" (free for commercial use),
or wait for a fully commercial-licensed replacement of equal accuracy.

See PROJECT_STATUS.md for the inspected architecture, validation status, and current
limitations. See PLANS.md for the proposed milestone roadmap.
