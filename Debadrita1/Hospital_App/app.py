from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3
import random
import string
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'aec_secure_key_v2'

# ==========================================
# DATABASE SETUP (Version 2)
# ==========================================
def get_db_connection():
    conn = sqlite3.connect('aec_hospital_v2.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS patients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, age INTEGER, disease TEXT, admitDate TEXT, dischargeDate TEXT, bill REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS appointments (id INTEGER PRIMARY KEY AUTOINCREMENT, patientName TEXT, doctorName TEXT, date TEXT, time TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS queue (id INTEGER PRIMARY KEY AUTOINCREMENT, tokenCode TEXT, patientName TEXT, counterName TEXT, disease TEXT, priority INTEGER, estimatedWait INTEGER, timeIn TEXT, status TEXT, counterId INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS counters (id INTEGER PRIMARY KEY, name TEXT, patientsServed INTEGER, totalServiceTime REAL, avgServiceTime REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)''')
    
    # Insert default counters
    if c.execute("SELECT COUNT(*) FROM counters").fetchone()[0] == 0:
        counters = [(1, "General OPD", 0, 0.0, 8.0), (2, "ENT", 0, 0.0, 10.0), (3, "Paediatrics", 0, 0.0, 7.0), (4, "Orthopaedics", 0, 0.0, 12.0)]
        c.executemany("INSERT INTO counters VALUES (?, ?, ?, ?, ?)", counters)
        
    # Insert default admin password
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        c.execute("INSERT INTO users (username, password) VALUES ('hospital', 'aec123')")
    
    conn.commit()
    conn.close()

# ==========================================
# LOGIN & LOGOUT
# ==========================================
@app.route('/')
def index():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    role_choice = request.form['role']
    if role_choice == '3':
        session['role'] = 'Patient'
        return redirect(url_for('dashboard'))
    
    username = request.form.get('username', '').strip().lower()
    password = request.form.get('password', '').strip()
    
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    
    if user and user['password'] == password:
        session['role'] = 'Admin' if role_choice == '1' else 'Doctor'
        return redirect(url_for('dashboard'))
        
    return "Invalid Credentials! Go back and try again."

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# ==========================================
# PASSWORD RECOVERY WORKFLOW
# ==========================================
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form.get('username').strip().lower()
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        
        if user:
            otp = str(random.randint(100000, 999999))
            session['reset_user'] = username
            session['otp'] = otp
            
            print("\n" + "="*50)
            print(f"🔐 SIMULATED EMAIL/SMS NOTIFICATION")
            print(f"Your AEC Hospital Password Reset OTP is: {otp}")
            print("="*50 + "\n")
            
            return redirect(url_for('verify_otp'))
        else:
            return "Username not found in system! Go back and try again."
    return render_template('forgot_password.html')

@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    if request.method == 'POST':
        entered_otp = request.form.get('otp').strip()
        if entered_otp == session.get('otp'):
            session['otp_verified'] = True
            return redirect(url_for('reset_password'))
        else:
            return "Invalid OTP! Go back and try again."
    return render_template('verify_otp.html')

@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if not session.get('otp_verified'):
        return redirect(url_for('forgot_password'))
        
    if request.method == 'POST':
        new_password = request.form.get('new_password').strip()
        username = session.get('reset_user')
        
        conn = get_db_connection()
        conn.execute("UPDATE users SET password = ? WHERE username = ?", (new_password, username))
        conn.commit()
        conn.close()
        
        session.clear()
        print("Password updated successfully!")
        return redirect(url_for('index'))
    return render_template('reset_password.html')

# ==========================================
# DASHBOARD & AI QUEUE LOGIC
# ==========================================
def predict_wait_time(queue_pos, counter_id, priority, current_hour):
    conn = get_db_connection()
    counter = conn.execute("SELECT * FROM counters WHERE id = ?", (counter_id,)).fetchone()
    q_len = conn.execute("SELECT COUNT(*) FROM queue WHERE counterName = ? AND status = 'Waiting'", (counter['name'],)).fetchone()[0]
    conn.close()

    base_wait = queue_pos * counter['avgServiceTime']
    peak_factor = 1.4 if (9 <= current_hour <= 11) or (15 <= current_hour <= 17) else (0.8 if 12 <= current_hour <= 14 else 1.0)
    if priority == 2: return 0
    priority_factor = 0.5 if priority == 1 else 1.0
    load_factor = 1.3 if q_len > 15 else (1.15 if q_len > 8 else 1.0)
    
    return max(int(base_wait * peak_factor * priority_factor * load_factor), 1)

@app.route('/dashboard')
def dashboard():
    if 'role' not in session: return redirect(url_for('index'))
    
    conn = get_db_connection()
    data = {
        'patients': conn.execute("SELECT * FROM patients").fetchall(),
        'appointments': conn.execute("SELECT * FROM appointments").fetchall(),
        'pending_queue': conn.execute("SELECT * FROM queue WHERE status='Pending' ORDER BY id ASC").fetchall(),
        'live_queue': conn.execute("SELECT * FROM queue WHERE status='Waiting' ORDER BY priority DESC, id ASC").fetchall(),
        'counters': conn.execute("SELECT * FROM counters").fetchall(),
        'my_tickets': []
    }
    
    if session['role'] == 'Patient' and 'patient_name' in session:
        data['my_tickets'] = conn.execute("SELECT * FROM queue WHERE patientName = ? ORDER BY id DESC", (session['patient_name'],)).fetchall()
        
    conn.close()
    return render_template('dashboard.html', role=session['role'], **data)

# ==========================================
# TOKEN APPROVAL & DELETION
# ==========================================
def generate_12_digit_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))

@app.route('/request_token', methods=['POST'])
def request_token():
    name = request.form['patientName']
    disease = request.form['disease']
    counter_id = int(request.form['counterId'])
    priority = int(request.form['priority'])
    
    session['patient_name'] = name 
    
    conn = get_db_connection()
    counter_name = conn.execute("SELECT name FROM counters WHERE id = ?", (counter_id,)).fetchone()[0]
    conn.execute("INSERT INTO queue (patientName, counterName, disease, priority, estimatedWait, status, counterId) VALUES (?, ?, ?, ?, ?, 'Pending', ?)",
                 (name, counter_name, disease, priority, 0, counter_id))
    conn.commit(); conn.close()
    return redirect(url_for('dashboard'))

@app.route('/approve_token/<int:req_id>')
def approve_token(req_id):
    if session.get('role') != 'Admin': return "Unauthorized"
    conn = get_db_connection()
    req = conn.execute("SELECT * FROM queue WHERE id = ?", (req_id,)).fetchone()
    token_code = generate_12_digit_code()
    pos = conn.execute("SELECT COUNT(*) FROM queue WHERE counterName = ? AND status='Waiting'", (req['counterName'],)).fetchone()[0] + 1
    wait = predict_wait_time(pos, req['counterId'], req['priority'], datetime.now().hour)
    conn.execute("UPDATE queue SET tokenCode = ?, estimatedWait = ?, timeIn = ?, status = 'Waiting' WHERE id = ?", 
                 (token_code, wait, datetime.now().strftime("%H:%M"), req_id))
    conn.commit(); conn.close()
    return redirect(url_for('dashboard'))

@app.route('/delete_token/<int:id>')
def delete_token(id):
    if session.get('role') != 'Patient': return "Unauthorized"
    conn = get_db_connection()
    conn.execute("DELETE FROM queue WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))

# ==========================================
# STANDARD HOSPITAL OPERATIONS
# ==========================================
@app.route('/add_patient', methods=['POST'])
def add_patient():
    data = request.form
    conn = get_db_connection()
    conn.execute("INSERT INTO patients (name, age, disease, admitDate, dischargeDate, bill) VALUES (?, ?, ?, ?, ?, ?)", (data['name'], data['age'], data['disease'], data['admitDate'], data['dischargeDate'], data['bill']))
    conn.commit(); conn.close()
    return redirect(url_for('dashboard'))

@app.route('/delete_patient/<int:id>')
def delete_patient(id):
    conn = get_db_connection()
    conn.execute("DELETE FROM patients WHERE id = ?", (id,))
    conn.commit(); conn.close()
    return redirect(url_for('dashboard'))

@app.route('/update_patient', methods=['POST'])
def update_patient():
    data = request.form
    conn = get_db_connection()
    conn.execute("UPDATE patients SET disease = ?, dischargeDate = ?, bill = ? WHERE id = ?", (data['disease'], data['dischargeDate'], data['bill'], data['id']))
    conn.commit(); conn.close()
    return redirect(url_for('dashboard'))

@app.route('/book_appointment', methods=['POST'])
def book_appointment():
    data = request.form
    conn = get_db_connection()
    conn.execute("INSERT INTO appointments (patientName, doctorName, date, time) VALUES (?, ?, ?, ?)", (data['patientName'], data['doctorName'], data['date'], data['time']))
    conn.commit(); conn.close()
    return redirect(url_for('dashboard'))

@app.route('/call_patient', methods=['POST'])
def call_patient():
    counter_id = request.form['counterId']
    conn = get_db_connection()
    counter_name = conn.execute("SELECT name FROM counters WHERE id = ?", (counter_id,)).fetchone()[0]
    next_patient = conn.execute("SELECT id FROM queue WHERE counterName = ? AND status = 'Waiting' ORDER BY priority DESC, id ASC LIMIT 1", (counter_name,)).fetchone()
    if next_patient:
        conn.execute("UPDATE queue SET status = 'Called' WHERE id = ?", (next_patient[0],))
        conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))

@app.route('/mark_complete', methods=['POST'])
def mark_complete():
    counter_id = request.form['counterId']
    actual_time = float(request.form['actualTime'])
    conn = get_db_connection()
    counter = conn.execute("SELECT * FROM counters WHERE id = ?", (counter_id,)).fetchone()
    served = counter['patientsServed']
    new_total = counter['totalServiceTime'] + actual_time
    conn.execute("UPDATE counters SET patientsServed = ?, totalServiceTime = ?, avgServiceTime = ? WHERE id = ?", (served + 1, new_total, new_total / (served + 1), counter_id))
    conn.execute("UPDATE queue SET status = 'Completed' WHERE counterName = ? AND status = 'Called'", (counter['name'],))
    conn.commit(); conn.close()
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)