# ClassVault – Academic Portal

A full-stack academic portal where **faculty upload materials** and **students download them**.  
Built with Python (zero dependencies) + SQLite + vanilla JS.

---

## Quick Start

### Requirements
- Python 3.8 or higher (standard library only – no pip install needed)

### Run
```bash
# Option 1: shell script
chmod +x start.sh
./start.sh

# Option 2: direct
python3 server.py
```

Then open **http://localhost:8080** in your browser.

---

## Demo Accounts

| Role    | Email                      | Password    |
|---------|----------------------------|-------------|
| Faculty | faculty@university.edu     | faculty123  |
| Student | student@university.edu     | student123  |

---

## Features

### Faculty
- ✅ Register / Login
- ✅ Create classrooms (code, name, sem, section)
- ✅ Upload files (real file storage, drag & drop)
- ✅ Categorise materials (Syllabus, Lessons, Model QPs, etc.)
- ✅ Post & delete announcements per classroom
- ✅ Delete uploaded materials
- ✅ Dashboard stats (classrooms, files, students, announcements)
- ✅ Update profile (name, department)

### Student
- ✅ Register / Login
- ✅ Browse and enroll in classrooms
- ✅ View materials by category (tabs)
- ✅ Download files (real file download)
- ✅ View announcements from all enrolled courses
- ✅ Download history tracking
- ✅ Dashboard stats

---

## API Reference

| Method | Endpoint                              | Auth     | Description             |
|--------|---------------------------------------|----------|-------------------------|
| POST   | /api/auth/login                       | –        | Login                   |
| POST   | /api/auth/register                    | –        | Register                |
| POST   | /api/auth/logout                      | Token    | Logout                  |
| PUT    | /api/me                               | Token    | Update profile          |
| GET    | /api/stats                            | Token    | Dashboard stats         |
| GET    | /api/classrooms                       | –        | All classrooms          |
| GET    | /api/my/classrooms                    | Token    | My classrooms           |
| POST   | /api/classrooms                       | Faculty  | Create classroom        |
| DELETE | /api/classrooms/:id                   | Faculty  | Delete classroom        |
| POST   | /api/classrooms/:id/enroll            | Student  | Enroll in classroom     |
| GET    | /api/classrooms/:id/materials         | –        | Get materials           |
| POST   | /api/classrooms/:id/materials         | Faculty  | Upload material         |
| GET    | /api/materials/:id/download           | –        | Download file           |
| DELETE | /api/materials/:id                    | Faculty  | Delete material         |
| GET    | /api/classrooms/:id/announcements     | –        | Get announcements       |
| POST   | /api/classrooms/:id/announcements     | Faculty  | Post announcement       |
| DELETE | /api/announcements/:id                | Faculty  | Delete announcement     |
| GET    | /api/my/downloads                     | Token    | Download history        |

---

## Project Structure
```
classvault/
├── server.py      ← Python backend (HTTP server + REST API)
├── index.html     ← Full frontend (single page app)
├── start.sh       ← Startup script
├── db/
│   └── classvault.db   ← SQLite database (auto-created)
└── uploads/            ← Uploaded files (auto-created)
```

---

## Deploy to Production

To deploy on a VPS or cloud server:

1. Copy the folder to your server
2. Run with: `python3 server.py`
3. Use **nginx** as a reverse proxy to port 8080
4. For HTTPS, add an SSL certificate via Let's Encrypt

### Nginx config example:
```nginx
server {
    listen 80;
    server_name yourdomain.com;
    location / {
        proxy_pass http://127.0.0.1:8080;
        client_max_body_size 100M;
    }
}
```
