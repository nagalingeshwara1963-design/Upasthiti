# Deploying Upasthiti Live on the Web

Upasthiti includes a modern **FastAPI Web Application** with an interactive dashboard, mobile phone & webcam support, real-time facial recognition, and attendance reporting.

---

## Option 1: Test & Run Locally (Immediate)

To test the web version right now on your machine:
1. Double-click:
   👉 **`Start_Web_Upasthiti.bat`**
2. Your browser will automatically open to:
   ```text
   http://localhost:8000
   ```
3. To open it on your **phone** connected to the same Wi-Fi:
   - Find your computer's IP address (run `ipconfig` in Command Prompt, e.g., `192.168.1.15`).
   - Open `http://192.168.1.15:8000` on your mobile browser!

---

## Option 2: Deploy Free to Render.com (Public HTTPS Web URL)

Render allows you to host this web application directly from your GitHub repository with a free public URL (`https://upasthiti-xxx.onrender.com`):

1. Go to [https://render.com](https://render.com) and log in with your GitHub account.
2. Click **New +** &rarr; **Web Service**.
3. Choose **Build and deploy from a Git repository**.
4. Select your repository: **`nagalingeshwara1963-design/Upasthiti`**.
5. Configure:
   - **Name**: `upasthiti-attendance`
   - **Runtime**: `Docker` (Render will automatically detect the `Dockerfile`)
   - **Instance Type**: `Free`
6. Click **Create Web Service**.
7. Render will build and deploy the container. Once finished, you will receive a live URL accessible to anyone on the internet!

---

## Option 3: Deploy Free to Hugging Face Spaces (Best for AI Models)

Hugging Face Spaces offers free 16 GB RAM CPU hosting specifically designed for AI/machine learning apps:

1. Go to [https://huggingface.co/spaces](https://huggingface.co/spaces) and sign up/log in.
2. Click **Create new Space**.
3. Set:
   - **Space name**: `upasthiti-attendance`
   - **License**: `MIT` or `OpenRAIL`
   - **Select the Space SDK**: **Docker** &rarr; **Blank**.
4. Once created, push your repository to your Hugging Face Space remote:
   ```bash
   git remote add space https://huggingface.co/spaces/YOUR_USERNAME/upasthiti-attendance
   git push space main
   ```
5. Your Space will build and be live with a permanent public link.
