#!/usr/bin/env python3
"""
ClassVault Backend Server
Full REST API with SQLite, file upload/download, JWT-like auth
Run: python3 server.py
"""

import http.server
import json
import sqlite3
import os
import hashlib
import secrets
import time
import re
import cgi
import shutil
import mimetypes
import urllib.parse
from pathlib import Path

DB_PATH = os.path.join(os.path.dirname(__file__), 'db', 'classvault.db')
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), 'uploads')
STATIC_DIR = os.path.dirname(__file__)
PORT = 8080

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# ─── Active sessions (token -> user_id) ───────────────────────────────────────
SESSIONS = {}

# ─── Database setup ───────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name     TEXT NOT NULL,
            email    TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role     TEXT NOT NULL CHECK(role IN ('faculty','student')),
            dept     TEXT DEFAULT '',
            created  INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS classrooms (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            code     TEXT NOT NULL,
            name     TEXT NOT NULL,
            sem      TEXT DEFAULT '',
            section  TEXT DEFAULT 'ALL',
            banner   INTEGER DEFAULT 0,
            owner_id INTEGER REFERENCES users(id),
            created  INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS enrollments (
            student_id   INTEGER REFERENCES users(id),
            classroom_id INTEGER REFERENCES classrooms(id),
            PRIMARY KEY (student_id, classroom_id)
        );

        CREATE TABLE IF NOT EXISTS materials (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            classroom_id INTEGER REFERENCES classrooms(id),
            uploader_id  INTEGER REFERENCES users(id),
            filename     TEXT NOT NULL,
            display_name TEXT NOT NULL,
            category     TEXT DEFAULT 'Other',
            description  TEXT DEFAULT '',
            size         INTEGER DEFAULT 0,
            filetype     TEXT DEFAULT 'pdf',
            created      INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS announcements (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            classroom_id INTEGER REFERENCES classrooms(id),
            author_id    INTEGER REFERENCES users(id),
            title        TEXT NOT NULL,
            body         TEXT NOT NULL,
            created      INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS downloads (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER REFERENCES users(id),
            material_id INTEGER REFERENCES materials(id),
            created     INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS enrollment_requests (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id   INTEGER REFERENCES users(id),
            classroom_id INTEGER REFERENCES classrooms(id),
            status       TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
            created      INTEGER DEFAULT (strftime('%s','now')),
            UNIQUE(student_id, classroom_id)
        );
    """)

    # Seed demo users
    pw_faculty = hashlib.sha256(b"faculty123").hexdigest()
    pw_student = hashlib.sha256(b"student123").hexdigest()
    conn.execute("INSERT OR IGNORE INTO users(name,email,password,role,dept) VALUES(?,?,?,?,?)",
                 ("Dr. Rajesh Kumar","faculty@university.edu",pw_faculty,"faculty","Computer Science"))
    conn.execute("INSERT OR IGNORE INTO users(name,email,password,role,dept) VALUES(?,?,?,?,?)",
                 ("Arun Selvam","student@university.edu",pw_student,"student","CSE"))

    fac = conn.execute("SELECT id FROM users WHERE email='faculty@university.edu'").fetchone()
    fac_id = fac['id']

    # Seed classrooms
    classes = [
        ("BECE309L","Artificial Intelligence and Machine Learning","Sem 5","ALL",0),
        ("CS301","Data Structures and Algorithms","Sem 3","A",1),
        ("EC205","Digital Signal Processing","Sem 4","B",2),
        ("MA101","Engineering Mathematics","Sem 1","ALL",3),
    ]
    for c in classes:
        exists = conn.execute("SELECT id FROM classrooms WHERE code=?", (c[0],)).fetchone()
        if not exists:
            conn.execute("INSERT INTO classrooms(code,name,sem,section,banner,owner_id) VALUES(?,?,?,?,?,?)",
                         (*c, fac_id))

    # Enroll demo student in all classrooms
    student = conn.execute("SELECT id FROM users WHERE email='student@university.edu'").fetchone()
    if student:
        for cls in conn.execute("SELECT id FROM classrooms").fetchall():
            conn.execute("INSERT OR IGNORE INTO enrollments VALUES(?,?)", (student['id'], cls['id']))

    # Seed materials
    cls1 = conn.execute("SELECT id FROM classrooms WHERE code='BECE309L'").fetchone()
    cls2 = conn.execute("SELECT id FROM classrooms WHERE code='CS301'").fetchone()
    if cls1:
        mats = [
            (cls1['id'], fac_id, "syllabus_bece309l.pdf","BECE309L_AIML_Syllabus.pdf","Syllabus","Complete syllabus with grading criteria",529000,"pdf"),
            (cls1['id'], fac_id, "unit1_intro_ai.pptx","Unit1_Introduction_to_AI.pptx","Lessons","Introduction to AI concepts",2300000,"ppt"),
            (cls1['id'], fac_id, "model_qp_nov2024.pdf","Model_QP_Nov2024.pdf","Model QPs","November 2024 model question paper",1100000,"pdf"),
            (cls1['id'], fac_id, "reference_books.pdf","Reference_Books_List.pdf","References","Reference books for the course",124000,"pdf"),
        ]
        for m in mats:
            exists = conn.execute("SELECT id FROM materials WHERE filename=?", (m[2],)).fetchone()
            if not exists:
                conn.execute("INSERT INTO materials(classroom_id,uploader_id,filename,display_name,category,description,size,filetype) VALUES(?,?,?,?,?,?,?,?)", m)
                # Create placeholder file
                fpath = os.path.join(UPLOAD_DIR, m[2])
                if not os.path.exists(fpath):
                    with open(fpath, 'wb') as f:
                        f.write(b"Demo file: " + m[3].encode())

    if cls2:
        mats2 = [
            (cls2['id'], fac_id, "dsa_syllabus.pdf","DSA_Syllabus_2025.pdf","Syllabus","Data Structures syllabus",310000,"pdf"),
            (cls2['id'], fac_id, "sorting_algorithms.pptx","Sorting_Algorithms.pptx","Lessons","Sorting algorithms lesson",3100000,"ppt"),
        ]
        for m in mats2:
            exists = conn.execute("SELECT id FROM materials WHERE filename=?", (m[2],)).fetchone()
            if not exists:
                conn.execute("INSERT INTO materials(classroom_id,uploader_id,filename,display_name,category,description,size,filetype) VALUES(?,?,?,?,?,?,?,?)", m)
                fpath = os.path.join(UPLOAD_DIR, m[2])
                if not os.path.exists(fpath):
                    with open(fpath, 'wb') as f:
                        f.write(b"Demo file: " + m[3].encode())

    # Seed announcements
    if cls1:
        anns = [
            (cls1['id'], fac_id, "Assignment 2 deadline extended", "Due to popular request, Assignment 2 deadline has been extended to Nov 30."),
            (cls1['id'], fac_id, "Extra class on Saturday", "Extra class this Saturday at 10 AM to cover Unit 4. Attendance is mandatory."),
        ]
        for a in anns:
            exists = conn.execute("SELECT id FROM announcements WHERE title=? AND classroom_id=?", (a[2], a[0])).fetchone()
            if not exists:
                conn.execute("INSERT INTO announcements(classroom_id,author_id,title,body) VALUES(?,?,?,?)", a)

    conn.commit()
    conn.close()
    print("✓ Database initialized")

# ─── Helpers ──────────────────────────────────────────────────────────────────
def json_response(handler, data, status=200):
    body = json.dumps(data).encode()
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Content-Length', len(body))
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.send_header('Access-Control-Allow-Methods', 'GET,POST,PUT,DELETE,OPTIONS')
    handler.send_header('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    handler.end_headers()
    handler.wfile.write(body)

def error(handler, msg, status=400):
    json_response(handler, {'error': msg}, status)

def get_token(handler):
    auth = handler.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        return auth[7:]
    return None

def get_user(handler):
    token = get_token(handler)
    if not token or token not in SESSIONS:
        return None
    uid, exp = SESSIONS[token]
    if time.time() > exp:
        del SESSIONS[token]
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    return dict(user) if user else None

def require_auth(handler, role=None):
    user = get_user(handler)
    if not user:
        error(handler, 'Unauthorized', 401)
        return None
    if role and user['role'] != role:
        error(handler, 'Forbidden', 403)
        return None
    return user

def format_size(b):
    if b < 1024: return f"{b} B"
    if b < 1024*1024: return f"{b//1024} KB"
    return f"{b//(1024*1024)} MB"

def guess_type(name):
    ext = name.rsplit('.',1)[-1].lower() if '.' in name else ''
    return {'pdf':'pdf','pptx':'ppt','ppt':'ppt','docx':'doc','doc':'doc',
            'zip':'zip','rar':'zip','mp4':'vid','avi':'vid','mov':'vid'}.get(ext,'pdf')

def fmt_date(ts):
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d') if ts else ''

def row_to_mat(m):
    return {
        'id': m['id'], 'classroomId': m['classroom_id'],
        'filename': m['filename'], 'displayName': m['display_name'],
        'category': m['category'], 'description': m['description'],
        'size': format_size(m['size']), 'filetype': m['filetype'],
        'date': fmt_date(m['created']),
    }

def row_to_class(c, mat_count=0, student_count=0):
    return {
        'id': c['id'], 'code': c['code'], 'name': c['name'],
        'sem': c['sem'], 'section': c['section'], 'banner': c['banner'],
        'ownerId': c['owner_id'], 'materialCount': mat_count,
        'studentCount': student_count,
    }

# ─── Request Handler ──────────────────────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,PUT,DELETE,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        # ── Static files ──
        if path == '/' or path == '/index.html':
            self.serve_file(os.path.join(STATIC_DIR, 'index.html'), 'text/html')
            return
        if path.endswith('.css'):
            self.serve_file(os.path.join(STATIC_DIR, path.lstrip('/')), 'text/css')
            return
        if path.endswith('.js') and not path.startswith('/api'):
            self.serve_file(os.path.join(STATIC_DIR, path.lstrip('/')), 'application/javascript')
            return

        # ── API routes ──
        if path == '/api/health':
            json_response(self, {'status': 'ok', 'time': int(time.time())})

        elif path == '/api/classrooms':
            self.api_get_classrooms()

        elif re.match(r'^/api/classrooms/\d+$', path):
            cid = int(path.split('/')[-1])
            self.api_get_classroom(cid)

        elif re.match(r'^/api/classrooms/\d+/materials$', path):
            cid = int(path.split('/')[-2])
            self.api_get_materials(cid, qs)

        elif re.match(r'^/api/classrooms/\d+/announcements$', path):
            cid = int(path.split('/')[-2])
            self.api_get_announcements(cid)

        elif re.match(r'^/api/materials/\d+/download$', path):
            mid = int(path.split('/')[-2])
            self.api_download(mid)

        elif path == '/api/me':
            user = require_auth(self)
            if user:
                json_response(self, {k: user[k] for k in ('id','name','email','role','dept')})

        elif path == '/api/my/classrooms':
            self.api_my_classrooms()

        elif path == '/api/my/enrollment-requests':
            self.api_my_enrollment_requests()

        elif re.match(r'^/api/classrooms/\d+/enrollment-requests$', path):
            cid = int(path.split('/')[-2])
            self.api_get_enrollment_requests(cid)

        elif path == '/api/my/downloads':
            self.api_my_downloads()

        elif path == '/api/stats':
            self.api_stats()

        else:
            error(self, 'Not found', 404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path

        if path == '/api/auth/login':
            self.api_login()
        elif path == '/api/auth/register':
            self.api_register()
        elif path == '/api/auth/logout':
            self.api_logout()
        elif path == '/api/classrooms':
            self.api_create_classroom()
        elif re.match(r'^/api/classrooms/\d+/materials$', path):
            cid = int(path.split('/')[-2])
            self.api_upload_material(cid)
        elif re.match(r'^/api/classrooms/\d+/announcements$', path):
            cid = int(path.split('/')[-2])
            self.api_post_announcement(cid)
        elif re.match(r'^/api/classrooms/\d+/enroll$', path):
            cid = int(path.split('/')[-2])
            self.api_enroll(cid)
        elif re.match(r'^/api/enrollment-requests/\d+/approve$', path):
            rid = int(path.split('/')[-2])
            self.api_approve_request(rid)
        elif re.match(r'^/api/enrollment-requests/\d+/reject$', path):
            rid = int(path.split('/')[-2])
            self.api_reject_request(rid)
        else:
            error(self, 'Not found', 404)

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        if re.match(r'^/api/materials/\d+$', path):
            mid = int(path.split('/')[-1])
            self.api_delete_material(mid)
        elif re.match(r'^/api/classrooms/\d+$', path):
            cid = int(path.split('/')[-1])
            self.api_delete_classroom(cid)
        elif re.match(r'^/api/announcements/\d+$', path):
            aid = int(path.split('/')[-1])
            self.api_delete_announcement(aid)
        elif re.match(r'^/api/classrooms/\d+/students/\d+$', path):
            parts = path.split('/')
            cid, sid = int(parts[-3]), int(parts[-1])
            self.api_remove_student(cid, sid)
        else:
            error(self, 'Not found', 404)

    def do_PUT(self):
        path = urllib.parse.urlparse(self.path).path
        if path == '/api/me':
            self.api_update_profile()
        else:
            error(self, 'Not found', 404)

    # ─── Static file server ─────────────────────────────────────────────────
    def serve_file(self, fpath, ctype):
        if not os.path.exists(fpath):
            error(self, 'File not found', 404)
            return
        with open(fpath, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', len(data))
        self.end_headers()
        self.wfile.write(data)

    # ─── Read body ──────────────────────────────────────────────────────────
    def read_json(self):
        length = int(self.headers.get('Content-Length', 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    # ─── Auth ───────────────────────────────────────────────────────────────
    def api_login(self):
        data = self.read_json()
        email = data.get('email','').strip().lower()
        password = data.get('password','')
        if not email or not password:
            return error(self, 'Email and password required')
        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email=? AND password=?", (email, pw_hash)).fetchone()
        conn.close()
        if not user:
            return error(self, 'Invalid credentials', 401)
        token = secrets.token_hex(32)
        SESSIONS[token] = (user['id'], time.time() + 86400 * 7)  # 7 days
        json_response(self, {
            'token': token,
            'user': {'id': user['id'], 'name': user['name'], 'email': user['email'],
                     'role': user['role'], 'dept': user['dept']}
        })

    def api_register(self):
        data = self.read_json()
        name = data.get('name','').strip()
        email = data.get('email','').strip().lower()
        password = data.get('password','')
        role = data.get('role','student')
        dept = data.get('dept','')
        if not name or not email or not password:
            return error(self, 'Name, email and password required')
        if role not in ('faculty','student'):
            return error(self, 'Invalid role')
        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        conn = get_db()
        try:
            cur = conn.execute("INSERT INTO users(name,email,password,role,dept) VALUES(?,?,?,?,?)",
                               (name, email, pw_hash, role, dept))
            uid = cur.lastrowid
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return error(self, 'Email already registered')
        conn.close()
        token = secrets.token_hex(32)
        SESSIONS[token] = (uid, time.time() + 86400 * 7)
        json_response(self, {'token': token, 'user': {'id': uid, 'name': name, 'email': email, 'role': role, 'dept': dept}}, 201)

    def api_logout(self):
        token = get_token(self)
        if token and token in SESSIONS:
            del SESSIONS[token]
        json_response(self, {'ok': True})

    def api_update_profile(self):
        user = require_auth(self)
        if not user: return
        data = self.read_json()
        name = data.get('name', user['name']).strip()
        dept = data.get('dept', user['dept']).strip()
        conn = get_db()
        conn.execute("UPDATE users SET name=?, dept=? WHERE id=?", (name, dept, user['id']))
        conn.commit()
        conn.close()
        json_response(self, {'ok': True, 'name': name, 'dept': dept})

    # ─── Classrooms ─────────────────────────────────────────────────────────
    def api_get_classrooms(self):
        conn = get_db()
        rows = conn.execute("SELECT * FROM classrooms ORDER BY created DESC").fetchall()
        result = []
        for c in rows:
            mc = conn.execute("SELECT COUNT(*) as n FROM materials WHERE classroom_id=?", (c['id'],)).fetchone()['n']
            sc = conn.execute("SELECT COUNT(*) as n FROM enrollments WHERE classroom_id=?", (c['id'],)).fetchone()['n']
            prof = conn.execute("SELECT name FROM users WHERE id=?", (c['owner_id'],)).fetchone()
            d = row_to_class(c, mc, sc)
            d['prof'] = prof['name'] if prof else 'Unknown'
            result.append(d)
        conn.close()
        json_response(self, result)

    def api_get_classroom(self, cid):
        conn = get_db()
        c = conn.execute("SELECT * FROM classrooms WHERE id=?", (cid,)).fetchone()
        if not c:
            conn.close()
            return error(self, 'Classroom not found', 404)
        mc = conn.execute("SELECT COUNT(*) as n FROM materials WHERE classroom_id=?", (cid,)).fetchone()['n']
        sc = conn.execute("SELECT COUNT(*) as n FROM enrollments WHERE classroom_id=?", (cid,)).fetchone()['n']
        prof = conn.execute("SELECT name FROM users WHERE id=?", (c['owner_id'],)).fetchone()
        d = row_to_class(c, mc, sc)
        d['prof'] = prof['name'] if prof else 'Unknown'
        conn.close()
        json_response(self, d)

    def api_my_classrooms(self):
        user = require_auth(self)
        if not user: return
        conn = get_db()
        if user['role'] == 'faculty':
            rows = conn.execute("SELECT * FROM classrooms WHERE owner_id=? ORDER BY created DESC", (user['id'],)).fetchall()
        else:
            rows = conn.execute("""
                SELECT c.* FROM classrooms c
                JOIN enrollments e ON e.classroom_id=c.id
                WHERE e.student_id=? ORDER BY c.created DESC
            """, (user['id'],)).fetchall()
        result = []
        for c in rows:
            mc = conn.execute("SELECT COUNT(*) as n FROM materials WHERE classroom_id=?", (c['id'],)).fetchone()['n']
            sc = conn.execute("SELECT COUNT(*) as n FROM enrollments WHERE classroom_id=?", (c['id'],)).fetchone()['n']
            prof = conn.execute("SELECT name FROM users WHERE id=?", (c['owner_id'],)).fetchone()
            d = row_to_class(c, mc, sc)
            d['prof'] = prof['name'] if prof else 'Unknown'
            result.append(d)
        conn.close()
        json_response(self, result)

    def api_create_classroom(self):
        user = require_auth(self, 'faculty')
        if not user: return
        data = self.read_json()
        code = data.get('code','').strip().upper()
        name = data.get('name','').strip()
        sem = data.get('sem','').strip()
        section = data.get('section','ALL').strip()
        if not code or not name:
            return error(self, 'Code and name required')
        conn = get_db()
        cur = conn.execute("INSERT INTO classrooms(code,name,sem,section,banner,owner_id) VALUES(?,?,?,?,?,?)",
                           (code, name, sem, section, len(conn.execute("SELECT id FROM classrooms").fetchall()) % 6, user['id']))
        cid = cur.lastrowid
        conn.commit()
        c = conn.execute("SELECT * FROM classrooms WHERE id=?", (cid,)).fetchone()
        conn.close()
        d = row_to_class(c, 0, 0)
        d['prof'] = user['name']
        json_response(self, d, 201)

    def api_delete_classroom(self, cid):
        user = require_auth(self, 'faculty')
        if not user: return
        conn = get_db()
        c = conn.execute("SELECT * FROM classrooms WHERE id=? AND owner_id=?", (cid, user['id'])).fetchone()
        if not c:
            conn.close()
            return error(self, 'Not found or not yours', 404)
        conn.execute("DELETE FROM materials WHERE classroom_id=?", (cid,))
        conn.execute("DELETE FROM announcements WHERE classroom_id=?", (cid,))
        conn.execute("DELETE FROM enrollments WHERE classroom_id=?", (cid,))
        conn.execute("DELETE FROM classrooms WHERE id=?", (cid,))
        conn.commit()
        conn.close()
        json_response(self, {'ok': True})

    def api_enroll(self, cid):
        user = require_auth(self, 'student')
        if not user: return
        conn = get_db()
        cls = conn.execute("SELECT id FROM classrooms WHERE id=?", (cid,)).fetchone()
        if not cls:
            conn.close()
            return error(self, 'Classroom not found', 404)
        # Check if already enrolled
        already = conn.execute("SELECT 1 FROM enrollments WHERE student_id=? AND classroom_id=?", (user['id'], cid)).fetchone()
        if already:
            conn.close()
            return error(self, 'Already enrolled', 409)
        # Check if already requested
        existing = conn.execute("SELECT status FROM enrollment_requests WHERE student_id=? AND classroom_id=?", (user['id'], cid)).fetchone()
        if existing:
            conn.close()
            return error(self, f'Request already {existing["status"]}', 409)
        conn.execute("INSERT INTO enrollment_requests(student_id, classroom_id, status) VALUES(?,?,?)", (user['id'], cid, 'pending'))
        conn.commit()
        conn.close()
        json_response(self, {'ok': True, 'status': 'pending'})

    # ─── Materials ──────────────────────────────────────────────────────────
    def api_get_materials(self, cid, qs):
        cat = qs.get('category', [None])[0]
        conn = get_db()
        if cat:
            rows = conn.execute("SELECT * FROM materials WHERE classroom_id=? AND category=? ORDER BY created DESC", (cid, cat)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM materials WHERE classroom_id=? ORDER BY created DESC", (cid,)).fetchall()
        conn.close()
        json_response(self, [row_to_mat(m) for m in rows])

    def api_upload_material(self, cid):
        user = require_auth(self, 'faculty')
        if not user: return

        content_type = self.headers.get('Content-Type', '')
        if 'multipart/form-data' not in content_type:
            return error(self, 'Expected multipart/form-data')

        # Parse multipart
        boundary = content_type.split('boundary=')[-1].encode()
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length)

        # Parse parts
        parts = raw.split(b'--' + boundary)
        fields = {}
        file_data = None
        file_name = None

        for part in parts[1:]:
            if part in (b'--\r\n', b'--'):
                continue
            if b'\r\n\r\n' not in part:
                continue
            header_raw, body = part.split(b'\r\n\r\n', 1)
            body = body.rstrip(b'\r\n')
            header_str = header_raw.decode('utf-8', errors='replace')
            disp = {}
            for seg in header_str.split(';'):
                seg = seg.strip()
                if '=' in seg:
                    k, v = seg.split('=', 1)
                    disp[k.strip()] = v.strip().strip('"')

            fname = disp.get('filename')
            field_name = disp.get('name', '')
            if fname:
                file_data = body
                file_name = fname
            else:
                fields[field_name] = body.decode('utf-8', errors='replace')

        if not file_data or not file_name:
            return error(self, 'No file uploaded')

        # Save file with unique name
        safe_name = re.sub(r'[^\w.\-]', '_', file_name)
        unique = f"{int(time.time())}_{secrets.token_hex(4)}_{safe_name}"
        fpath = os.path.join(UPLOAD_DIR, unique)
        with open(fpath, 'wb') as f:
            f.write(file_data)

        display_name = fields.get('displayName', file_name)
        category = fields.get('category', 'Other')
        description = fields.get('description', '')
        size = len(file_data)
        ftype = guess_type(file_name)

        conn = get_db()
        cur = conn.execute(
            "INSERT INTO materials(classroom_id,uploader_id,filename,display_name,category,description,size,filetype) VALUES(?,?,?,?,?,?,?,?)",
            (cid, user['id'], unique, display_name, category, description, size, ftype)
        )
        mid = cur.lastrowid
        conn.commit()
        m = conn.execute("SELECT * FROM materials WHERE id=?", (mid,)).fetchone()
        conn.close()
        json_response(self, row_to_mat(m), 201)

    def api_download(self, mid):
        user = get_user(self)
        conn = get_db()
        m = conn.execute("SELECT * FROM materials WHERE id=?", (mid,)).fetchone()
        if not m:
            conn.close()
            return error(self, 'Material not found', 404)

        if user:
            conn.execute("INSERT INTO downloads(user_id,material_id) VALUES(?,?)", (user['id'], mid))
            conn.commit()
        conn.close()

        fpath = os.path.join(UPLOAD_DIR, m['filename'])
        if not os.path.exists(fpath):
            return error(self, 'File not found on server', 404)

        with open(fpath, 'rb') as f:
            data = f.read()

        mime, _ = mimetypes.guess_type(m['display_name'])
        mime = mime or 'application/octet-stream'

        disp_name = urllib.parse.quote(m['display_name'])
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', len(data))
        self.send_header('Content-Disposition', f'attachment; filename="{m["display_name"]}"; filename*=UTF-8\'\'{disp_name}')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data)

    def api_delete_material(self, mid):
        user = require_auth(self, 'faculty')
        if not user: return
        conn = get_db()
        m = conn.execute("SELECT * FROM materials WHERE id=? AND uploader_id=?", (mid, user['id'])).fetchone()
        if not m:
            conn.close()
            return error(self, 'Not found or not yours', 404)
        fpath = os.path.join(UPLOAD_DIR, m['filename'])
        if os.path.exists(fpath):
            os.remove(fpath)
        conn.execute("DELETE FROM downloads WHERE material_id=?", (mid,))
        conn.execute("DELETE FROM materials WHERE id=?", (mid,))
        conn.commit()
        conn.close()
        json_response(self, {'ok': True})

    # ─── Announcements ──────────────────────────────────────────────────────
    def api_get_announcements(self, cid):
        conn = get_db()
        rows = conn.execute("""
            SELECT a.*, u.name as author_name
            FROM announcements a JOIN users u ON u.id=a.author_id
            WHERE a.classroom_id=? ORDER BY a.created DESC
        """, (cid,)).fetchall()
        conn.close()
        result = []
        for a in rows:
            result.append({'id': a['id'], 'classroomId': a['classroom_id'],
                           'title': a['title'], 'body': a['body'],
                           'author': a['author_name'], 'date': fmt_date(a['created'])})
        json_response(self, result)

    def api_post_announcement(self, cid):
        user = require_auth(self, 'faculty')
        if not user: return
        data = self.read_json()
        title = data.get('title','').strip()
        body = data.get('body','').strip()
        if not title or not body:
            return error(self, 'Title and body required')
        conn = get_db()
        cur = conn.execute("INSERT INTO announcements(classroom_id,author_id,title,body) VALUES(?,?,?,?)",
                           (cid, user['id'], title, body))
        aid = cur.lastrowid
        conn.commit()
        a = conn.execute("SELECT a.*, u.name as author_name FROM announcements a JOIN users u ON u.id=a.author_id WHERE a.id=?", (aid,)).fetchone()
        conn.close()
        json_response(self, {'id': a['id'], 'classroomId': a['classroom_id'],
                             'title': a['title'], 'body': a['body'],
                             'author': a['author_name'], 'date': fmt_date(a['created'])}, 201)

    def api_delete_announcement(self, aid):
        user = require_auth(self, 'faculty')
        if not user: return
        conn = get_db()
        a = conn.execute("SELECT * FROM announcements WHERE id=? AND author_id=?", (aid, user['id'])).fetchone()
        if not a:
            conn.close()
            return error(self, 'Not found or not yours', 404)
        conn.execute("DELETE FROM announcements WHERE id=?", (aid,))
        conn.commit()
        conn.close()
        json_response(self, {'ok': True})

    # ─── Downloads history ──────────────────────────────────────────────────
    def api_my_downloads(self):
        user = require_auth(self)
        if not user: return
        conn = get_db()
        rows = conn.execute("""
            SELECT d.*, m.display_name, m.filetype, m.category, c.code as class_code
            FROM downloads d
            JOIN materials m ON m.id=d.material_id
            JOIN classrooms c ON c.id=m.classroom_id
            WHERE d.user_id=? ORDER BY d.created DESC LIMIT 50
        """, (user['id'],)).fetchall()
        conn.close()
        result = [{'id': r['id'], 'materialId': r['material_id'], 'name': r['display_name'],
                   'filetype': r['filetype'], 'category': r['category'],
                   'classCode': r['class_code'], 'date': fmt_date(r['created'])} for r in rows]
        json_response(self, result)

    # ─── Stats ──────────────────────────────────────────────────────────────
    def api_stats(self):
        user = require_auth(self)
        if not user: return
        conn = get_db()
        if user['role'] == 'faculty':
            classes = conn.execute("SELECT COUNT(*) as n FROM classrooms WHERE owner_id=?", (user['id'],)).fetchone()['n']
            files = conn.execute("""
                SELECT COUNT(*) as n FROM materials m
                JOIN classrooms c ON c.id=m.classroom_id WHERE c.owner_id=?
            """, (user['id'],)).fetchone()['n']
            students = conn.execute("""
                SELECT COUNT(DISTINCT e.student_id) as n FROM enrollments e
                JOIN classrooms c ON c.id=e.classroom_id WHERE c.owner_id=?
            """, (user['id'],)).fetchone()['n']
            anns = conn.execute("""
                SELECT COUNT(*) as n FROM announcements WHERE author_id=?
            """, (user['id'],)).fetchone()['n']
            pending = conn.execute("""
                SELECT COUNT(*) as n FROM enrollment_requests er
                JOIN classrooms c ON c.id=er.classroom_id
                WHERE c.owner_id=? AND er.status='pending'
            """, (user['id'],)).fetchone()['n']
            conn.close()
            json_response(self, {'classes': classes, 'files': files, 'students': students, 'announcements': anns, 'pendingRequests': pending})
        else:
            classes = conn.execute("SELECT COUNT(*) as n FROM enrollments WHERE student_id=?", (user['id'],)).fetchone()['n']
            files = conn.execute("""
                SELECT COUNT(*) as n FROM materials m
                JOIN enrollments e ON e.classroom_id=m.classroom_id WHERE e.student_id=?
            """, (user['id'],)).fetchone()['n']
            downloads = conn.execute("SELECT COUNT(*) as n FROM downloads WHERE user_id=?", (user['id'],)).fetchone()['n']
            anns = conn.execute("""
                SELECT COUNT(*) as n FROM announcements a
                JOIN enrollments e ON e.classroom_id=a.classroom_id WHERE e.student_id=?
            """, (user['id'],)).fetchone()['n']
            conn.close()
            json_response(self, {'classes': classes, 'files': files, 'downloads': downloads, 'announcements': anns})


    def api_my_enrollment_requests(self):
        user = require_auth(self, 'student')
        if not user: return
        conn = get_db()
        rows = conn.execute("""
            SELECT er.*, c.code, c.name as cls_name, u.name as faculty_name
            FROM enrollment_requests er
            JOIN classrooms c ON c.id = er.classroom_id
            JOIN users u ON u.id = c.owner_id
            WHERE er.student_id = ? ORDER BY er.created DESC
        """, (user['id'],)).fetchall()
        conn.close()
        result = [{'id': r['id'], 'classroomId': r['classroom_id'], 'code': r['code'],
                   'name': r['cls_name'], 'faculty': r['faculty_name'],
                   'status': r['status'], 'date': fmt_date(r['created'])} for r in rows]
        json_response(self, result)

    def api_get_enrollment_requests(self, cid):
        user = require_auth(self, 'faculty')
        if not user: return
        conn = get_db()
        # Verify ownership
        cls = conn.execute("SELECT id FROM classrooms WHERE id=? AND owner_id=?", (cid, user['id'])).fetchone()
        if not cls:
            conn.close()
            return error(self, 'Not found or not yours', 404)
        rows = conn.execute("""
            SELECT er.*, u.name as student_name, u.email as student_email, u.dept as student_dept
            FROM enrollment_requests er
            JOIN users u ON u.id = er.student_id
            WHERE er.classroom_id = ? ORDER BY er.created DESC
        """, (cid,)).fetchall()
        conn.close()
        result = [{'id': r['id'], 'studentId': r['student_id'], 'studentName': r['student_name'],
                   'studentEmail': r['student_email'], 'dept': r['student_dept'],
                   'status': r['status'], 'date': fmt_date(r['created'])} for r in rows]
        json_response(self, result)

    def api_approve_request(self, rid):
        user = require_auth(self, 'faculty')
        if not user: return
        conn = get_db()
        req = conn.execute("""
            SELECT er.* FROM enrollment_requests er
            JOIN classrooms c ON c.id = er.classroom_id
            WHERE er.id = ? AND c.owner_id = ?
        """, (rid, user['id'])).fetchone()
        if not req:
            conn.close()
            return error(self, 'Request not found or not yours', 404)
        conn.execute("UPDATE enrollment_requests SET status='approved' WHERE id=?", (rid,))
        conn.execute("INSERT OR IGNORE INTO enrollments VALUES(?,?)", (req['student_id'], req['classroom_id']))
        conn.commit()
        conn.close()
        json_response(self, {'ok': True})

    def api_reject_request(self, rid):
        user = require_auth(self, 'faculty')
        if not user: return
        conn = get_db()
        req = conn.execute("""
            SELECT er.* FROM enrollment_requests er
            JOIN classrooms c ON c.id = er.classroom_id
            WHERE er.id = ? AND c.owner_id = ?
        """, (rid, user['id'])).fetchone()
        if not req:
            conn.close()
            return error(self, 'Request not found or not yours', 404)
        conn.execute("UPDATE enrollment_requests SET status='rejected' WHERE id=?", (rid,))
        conn.commit()
        conn.close()
        json_response(self, {'ok': True})


    def api_remove_student(self, cid, sid):
        user = require_auth(self, 'faculty')
        if not user: return
        conn = get_db()
        cls = conn.execute("SELECT id FROM classrooms WHERE id=? AND owner_id=?", (cid, user['id'])).fetchone()
        if not cls:
            conn.close()
            return error(self, 'Not found or not yours', 404)
        conn.execute("DELETE FROM enrollments WHERE student_id=? AND classroom_id=?", (sid, cid))
        conn.execute("UPDATE enrollment_requests SET status='rejected' WHERE student_id=? AND classroom_id=?", (sid, cid))
        conn.commit()
        conn.close()
        json_response(self, {'ok': True})

# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    server = http.server.ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    print(f"""
╔══════════════════════════════════════════╗
║        ClassVault Backend Running        ║
║  http://localhost:{PORT}                    ║
║                                          ║
║  Demo Faculty: faculty@university.edu    ║
║  Demo Student: student@university.edu    ║
║  Password:     faculty123 / student123   ║
╚══════════════════════════════════════════╝
""")
    server.serve_forever()
