import sqlite3
import os
from datetime import datetime
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify, g)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# Secret key: set SECRET_KEY env variable in production (PythonAnywhere / Render)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-only-change-in-production')

# Database: set DB_PATH env variable in production, otherwise use local file
DATABASE = os.environ.get('DB_PATH', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'legal.db'))

# ─────────────────────────────────────────────
# HARDCODED SINGLE-ADVOCATE PROFILE
# ─────────────────────────────────────────────
ADVOCATE = {
    'name':        'Gaurav Raj Bhagat',
    'email':       'gaurav@lexconnect.in',
    'designation': 'Advocate, Supreme Court of India',
    'location':    '123, Law Avenue, Delhi',
    'fees':        1500,
    'weekly_off':  'Sunday',
    'court_level': 'Supreme Court',
    'bio':         'Senior advocate with extensive experience before the Supreme Court of India.',
    'meeting_time_slots': '09:00 AM – 11:00 AM, 11:00 AM – 01:00 PM, 02:00 PM – 04:00 PM, 05:00 PM – 07:00 PM',
}

# Will be populated after DB init
ADVOCATE_ID = None

# ─────────────────────────────────────────────
# DATABASE HELPERS
# ─────────────────────────────────────────────

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


def execute_db(query, args=()):
    db = get_db()
    cur = db.execute(query, args)
    db.commit()
    return cur.lastrowid


# ─────────────────────────────────────────────
# DB INITIALISATION
# ─────────────────────────────────────────────

def init_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.executescript("""
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name     TEXT    NOT NULL,
            email    TEXT    NOT NULL UNIQUE,
            password TEXT    NOT NULL,
            role     TEXT    NOT NULL CHECK(role IN ('client','advocate'))
        );

        CREATE TABLE IF NOT EXISTS advocates (
            user_id            INTEGER PRIMARY KEY REFERENCES users(id),
            court_level        TEXT DEFAULT '',
            location           TEXT DEFAULT '',
            fees               REAL DEFAULT 0,
            bio                TEXT DEFAULT '',
            meeting_time_slots TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS appointments (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id      INTEGER REFERENCES users(id),
            advocate_id    INTEGER REFERENCES users(id),
            date           TEXT    NOT NULL,
            time           TEXT    NOT NULL,
            mode           TEXT    NOT NULL CHECK(mode IN ('Online','Offline')),
            status         TEXT    NOT NULL DEFAULT 'Pending'
                                   CHECK(status IN ('Pending','Accepted','Rejected')),
            payment_status TEXT    NOT NULL DEFAULT 'Pending'
                                   CHECK(payment_status IN ('Pending','Paid'))
        );

        CREATE TABLE IF NOT EXISTS messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_id INTEGER REFERENCES appointments(id),
            sender_id    INTEGER REFERENCES users(id),
            message_text TEXT    NOT NULL,
            timestamp    TEXT    NOT NULL
        );
    """)
    db.commit()
    db.close()
    print("[OK] Database initialised.")


def seed_advocate():
    """Ensure Gaurav Raj Bhagat exists in DB and cache his user_id in ADVOCATE_ID."""
    global ADVOCATE_ID
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row

    row = db.execute(
        'SELECT id FROM users WHERE email = ?', [ADVOCATE['email']]
    ).fetchone()

    if row:
        uid = row['id']
    else:
        from werkzeug.security import generate_password_hash
        hashed = generate_password_hash('ChangeMe@123')  # placeholder password
        cur = db.execute(
            'INSERT INTO users (name, email, password, role) VALUES (?,?,?,?)',
            [ADVOCATE['name'], ADVOCATE['email'], hashed, 'advocate']
        )
        uid = cur.lastrowid
        db.execute(
            """INSERT INTO advocates
               (user_id, court_level, location, fees, bio, meeting_time_slots)
               VALUES (?,?,?,?,?,?)""",
            [uid, ADVOCATE['court_level'], ADVOCATE['location'],
             ADVOCATE['fees'], ADVOCATE['bio'], ADVOCATE['meeting_time_slots']]
        )
        db.commit()
        print(f"[OK] Advocate seeded with id={uid}")

    # Always keep advocates row in sync with hardcoded data
    db.execute(
        """UPDATE advocates SET court_level=?, location=?, fees=?,
           bio=?, meeting_time_slots=? WHERE user_id=?""",
        [ADVOCATE['court_level'], ADVOCATE['location'], ADVOCATE['fees'],
         ADVOCATE['bio'], ADVOCATE['meeting_time_slots'], uid]
    )
    db.commit()
    db.close()
    ADVOCATE_ID = uid
    print(f"[OK] ADVOCATE_ID = {ADVOCATE_ID}")


# ─────────────────────────────────────────────
# AUTH DECORATORS
# ─────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def role_required(role):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get('role') != role:
                flash('Unauthorised access.', 'danger')
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated
    return decorator


# ─────────────────────────────────────────────
# ROOT
# ─────────────────────────────────────────────

@app.route('/')
def index():
    if 'user_id' in session:
        if session['role'] == 'client':
            return redirect(url_for('client_dashboard'))
        return redirect(url_for('advocate_dashboard'))
    return redirect(url_for('login'))


# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name     = request.form['name'].strip()
        email    = request.form['email'].strip().lower()
        password = request.form['password']
        role     = request.form['role']

        if not name or not email or not password:
            flash('All fields are required.', 'danger')
            return redirect(url_for('register'))

        # Always register as client – advocate onboarding removed
        role = 'client'

        existing = query_db('SELECT id FROM users WHERE email = ?', [email], one=True)
        if existing:
            flash('Email already registered. Please log in.', 'warning')
            return redirect(url_for('login'))

        hashed = generate_password_hash(password)
        uid = execute_db(
            'INSERT INTO users (name, email, password, role) VALUES (?,?,?,?)',
            [name, email, hashed, role]
        )

        if role == 'advocate':
            execute_db('INSERT INTO advocates (user_id) VALUES (?)', [uid])

        session.clear()
        session['user_id'] = uid
        session['name']    = name
        session['role']    = 'client'  # always client – advocate onboarding removed
        flash(f'Welcome, {name}! Account created.', 'success')
        return redirect(url_for('client_dashboard'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form['email'].strip().lower()
        password = request.form['password']

        user = query_db('SELECT * FROM users WHERE email = ?', [email], one=True)
        if not user or not check_password_hash(user['password'], password):
            flash('Invalid email or password.', 'danger')
            return redirect(url_for('login'))

        session.clear()
        session['user_id'] = user['id']
        session['name']    = user['name']
        session['role']    = user['role']
        flash(f'Welcome back, {user["name"]}!', 'success')

        if user['role'] == 'advocate':
            return redirect(url_for('advocate_dashboard'))
        return redirect(url_for('client_dashboard'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# ─────────────────────────────────────────────
# CLIENT ROUTES
# ─────────────────────────────────────────────

@app.route('/client/dashboard')
@login_required
@role_required('client')
def client_dashboard():
    uid = session['user_id']
    upcoming = query_db(
        """SELECT COUNT(*) as cnt FROM appointments
           WHERE client_id=? AND status='Accepted'
             AND date >= date('now')""", [uid], one=True)
    total = query_db(
        'SELECT COUNT(*) as cnt FROM appointments WHERE client_id=?', [uid], one=True)
    pending = query_db(
        "SELECT COUNT(*) as cnt FROM appointments WHERE client_id=? AND status='Pending'",
        [uid], one=True)
    return render_template('client/dashboard.html',
                           upcoming=upcoming['cnt'],
                           total=total['cnt'],
                           pending=pending['cnt'],
                           adv_id=ADVOCATE_ID)


@app.route('/client/search')
@login_required
@role_required('client')
def client_search():
    # Single-advocate mode: redirect straight to this advocate's profile
    return redirect(url_for('advocate_profile', adv_id=ADVOCATE_ID))


@app.route('/client/advocate/<int:adv_id>')
@login_required
@role_required('client')
def advocate_profile(adv_id):
    adv = query_db(
        """SELECT u.id, u.name, u.email, a.court_level, a.location,
                  a.fees, a.bio, a.meeting_time_slots
           FROM users u JOIN advocates a ON u.id = a.user_id
           WHERE u.id = ?""", [adv_id], one=True)
    if not adv:
        flash('Advocate not found.', 'danger')
        return redirect(url_for('client_search'))
    slots = [s.strip() for s in adv['meeting_time_slots'].split(',') if s.strip()]
    return render_template('client/advocate_profile.html', adv=adv, slots=slots)


@app.route('/client/book/<int:adv_id>', methods=['GET', 'POST'])
@login_required
@role_required('client')
def book_appointment(adv_id):
    adv = query_db(
        """SELECT u.id, u.name, a.fees, a.meeting_time_slots
           FROM users u JOIN advocates a ON u.id = a.user_id
           WHERE u.id = ?""", [adv_id], one=True)
    if not adv:
        flash('Advocate not found.', 'danger')
        return redirect(url_for('client_search'))

    slots = [s.strip() for s in adv['meeting_time_slots'].split(',') if s.strip()]

    if request.method == 'POST':
        date = request.form['date']
        time = request.form['time']
        mode = request.form['mode']

        if not date or not time or mode not in ('Online', 'Offline'):
            flash('Please fill all booking details.', 'danger')
            return redirect(request.url)

        execute_db(
            """INSERT INTO appointments
               (client_id, advocate_id, date, time, mode, status, payment_status)
               VALUES (?,?,?,?,?,'Pending','Pending')""",
            [session['user_id'], adv_id, date, time, mode]
        )
        flash('Appointment booked successfully! Awaiting advocate confirmation.', 'success')
        return redirect(url_for('my_appointments'))

    return render_template('client/book.html', adv=adv, slots=slots)


@app.route('/client/appointments')
@login_required
@role_required('client')
def my_appointments():
    uid = session['user_id']
    appts = query_db(
        """SELECT ap.*, u.name AS advocate_name, u.email AS advocate_email
           FROM appointments ap JOIN users u ON ap.advocate_id = u.id
           WHERE ap.client_id = ?
           ORDER BY ap.date DESC, ap.time DESC""", [uid])
    return render_template('client/my_appointments.html', appointments=appts)


@app.route('/client/pay/<int:appt_id>', methods=['POST'])
@login_required
@role_required('client')
def pay_appointment(appt_id):
    appt = query_db(
        'SELECT * FROM appointments WHERE id=? AND client_id=?',
        [appt_id, session['user_id']], one=True)
    if not appt:
        return jsonify({'success': False, 'error': 'Appointment not found'}), 404
    execute_db(
        "UPDATE appointments SET payment_status='Paid' WHERE id=?", [appt_id])
    return jsonify({'success': True})


# ─────────────────────────────────────────────
# ADVOCATE ROUTES
# ─────────────────────────────────────────────

@app.route('/advocate/dashboard')
@login_required
@role_required('advocate')
def advocate_dashboard():
    uid = session['user_id']
    pending = query_db(
        "SELECT COUNT(*) as cnt FROM appointments WHERE advocate_id=? AND status='Pending'",
        [uid], one=True)
    accepted = query_db(
        "SELECT COUNT(*) as cnt FROM appointments WHERE advocate_id=? AND status='Accepted'",
        [uid], one=True)
    total = query_db(
        'SELECT COUNT(*) as cnt FROM appointments WHERE advocate_id=?', [uid], one=True)
    profile = query_db('SELECT * FROM advocates WHERE user_id=?', [uid], one=True)
    return render_template('advocate/dashboard.html',
                           pending=pending['cnt'],
                           accepted=accepted['cnt'],
                           total=total['cnt'],
                           profile=profile)


@app.route('/advocate/profile', methods=['GET', 'POST'])
@login_required
@role_required('advocate')
def advocate_profile_setup():
    uid = session['user_id']
    if request.method == 'POST':
        courts = request.form.getlist('court_level')
        court_str = ', '.join(courts)
        location = request.form['location'].strip()
        fees     = request.form['fees'].strip()
        bio      = request.form['bio'].strip()
        slots    = request.form['meeting_time_slots'].strip()

        try:
            fees = float(fees)
        except ValueError:
            fees = 0.0

        execute_db(
            """UPDATE advocates SET court_level=?, location=?, fees=?,
               bio=?, meeting_time_slots=? WHERE user_id=?""",
            [court_str, location, fees, bio, slots, uid]
        )
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('advocate_dashboard'))

    profile = query_db('SELECT * FROM advocates WHERE user_id=?', [uid], one=True)
    return render_template('advocate/profile_setup.html', profile=profile)


@app.route('/advocate/appointments')
@login_required
@role_required('advocate')
def manage_appointments():
    uid = session['user_id']
    appts = query_db(
        """SELECT ap.*, u.name AS client_name, u.email AS client_email
           FROM appointments ap JOIN users u ON ap.client_id = u.id
           WHERE ap.advocate_id = ?
           ORDER BY ap.date DESC, ap.time DESC""", [uid])
    return render_template('advocate/manage_appointments.html', appointments=appts)


@app.route('/advocate/respond/<int:appt_id>', methods=['POST'])
@login_required
@role_required('advocate')
def respond_appointment(appt_id):
    action = request.form.get('action')  # 'Accept' or 'Reject'
    if action not in ('Accepted', 'Rejected'):
        flash('Invalid action.', 'danger')
        return redirect(url_for('manage_appointments'))

    appt = query_db(
        'SELECT * FROM appointments WHERE id=? AND advocate_id=?',
        [appt_id, session['user_id']], one=True)
    if not appt:
        flash('Appointment not found.', 'danger')
        return redirect(url_for('manage_appointments'))

    execute_db('UPDATE appointments SET status=? WHERE id=?', [action, appt_id])
    flash(f'Appointment {action}.', 'success')
    return redirect(url_for('manage_appointments'))


# ─────────────────────────────────────────────
# CHAT (SHARED)
# ─────────────────────────────────────────────

def can_access_chat(appt_id, user_id):
    """Returns the appointment if the user is the client or advocate on it."""
    return query_db(
        """SELECT * FROM appointments
           WHERE id=? AND (client_id=? OR advocate_id=?)
             AND status='Accepted' AND mode='Online'""",
        [appt_id, user_id, user_id], one=True)


@app.route('/chat/<int:appt_id>')
@login_required
def chat_room(appt_id):
    appt = can_access_chat(appt_id, session['user_id'])
    if not appt:
        flash('Chat is only available for Accepted Online appointments.', 'warning')
        if session['role'] == 'client':
            return redirect(url_for('my_appointments'))
        return redirect(url_for('manage_appointments'))

    # Load participant names
    client = query_db('SELECT name FROM users WHERE id=?', [appt['client_id']], one=True)
    advocate = query_db('SELECT name FROM users WHERE id=?', [appt['advocate_id']], one=True)

    messages = query_db(
        """SELECT m.*, u.name AS sender_name FROM messages m
           JOIN users u ON m.sender_id = u.id
           WHERE m.appointment_id = ?
           ORDER BY m.timestamp ASC""", [appt_id])

    return render_template('chat.html',
                           appt=appt,
                           messages=messages,
                           client_name=client['name'],
                           advocate_name=advocate['name'])


@app.route('/chat/send/<int:appt_id>', methods=['POST'])
@login_required
def chat_send(appt_id):
    appt = can_access_chat(appt_id, session['user_id'])
    if not appt:
        return jsonify({'error': 'Unauthorised'}), 403

    data = request.get_json()
    text = (data or {}).get('message', '').strip()
    if not text:
        return jsonify({'error': 'Empty message'}), 400

    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    execute_db(
        'INSERT INTO messages (appointment_id, sender_id, message_text, timestamp) VALUES (?,?,?,?)',
        [appt_id, session['user_id'], text, ts]
    )
    return jsonify({'success': True, 'timestamp': ts})


@app.route('/chat/poll/<int:appt_id>')
@login_required
def chat_poll(appt_id):
    appt = can_access_chat(appt_id, session['user_id'])
    if not appt:
        return jsonify({'error': 'Unauthorised'}), 403

    since = request.args.get('since', '1970-01-01 00:00:00')
    msgs = query_db(
        """SELECT m.id, m.message_text, m.timestamp, u.name AS sender_name,
                  m.sender_id
           FROM messages m JOIN users u ON m.sender_id = u.id
           WHERE m.appointment_id = ? AND m.timestamp > ?
           ORDER BY m.timestamp ASC""", [appt_id, since])

    result = [dict(m) for m in msgs]
    return jsonify({'messages': result})


# ─────────────────────────────────────────────
# HELP PAGE
# ─────────────────────────────────────────────

@app.route('/help')
def help_page():
    return render_template('help.html')


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    seed_advocate()
    app.run(debug=True, port=5000)
