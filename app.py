from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, send_file
from flask_mail import Mail, Message
import pytz, random, os, time, sqlite3, requests, io
from datetime import datetime
import qrcode

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# ✅ Robots.txt & Sitemap.xml
@app.route("/robots.txt")
def robots():
    return send_from_directory("static", "robots.txt")

@app.route("/sitemap.xml")
def sitemap():
    return send_from_directory("static", "sitemap.xml")

# ✅ Maintenance Mode Logic
@app.before_request
def check_maintenance():
    allowed_routes = ['maintenance', 'static', 'robots', 'sitemap']
    if os.getenv('MAINTENANCE_MODE', 'off') == 'on':
        if request.endpoint not in allowed_routes and not request.path.startswith("/static"):
            return render_template("maintenance.html"), 503

# ✅ Mail Config (fallback to default if env missing)
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USE_SSL=False,
    MAIL_USERNAME=os.getenv('MAIL_USERNAME', 'your_email@gmail.com'),
    MAIL_PASSWORD=os.getenv('MAIL_PASSWORD', 'your_app_password'),
    MAIL_DEFAULT_SENDER=os.getenv('MAIL_USERNAME', 'your_email@gmail.com')
)
mail = Mail(app)

# ✅ SQLite DB Setup
def init_db():
    with sqlite3.connect('users.db') as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                last_login TIMESTAMP
            )
        ''')
init_db()

def get_last_login(email):
    with sqlite3.connect('users.db') as conn:
        row = conn.execute("SELECT last_login FROM users WHERE email=?", (email,)).fetchone()
        return datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S') if row else None

def update_last_login(email):
    now = datetime.now(pytz.timezone("Asia/Kolkata")).strftime('%Y-%m-%d %H:%M:%S')
    with sqlite3.connect('users.db') as conn:
        conn.execute("INSERT OR REPLACE INTO users (email, last_login) VALUES (?, ?)", (email, now))

# ✅ Google Sheet Logger
def send_to_google_script(email, status):
    try:
        login_time = session.get('login_time') or datetime.now(pytz.timezone("Asia/Kolkata"))
        data = {
            "email": email,
            "time": login_time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": status
        }
        requests.post("https://script.google.com/macros/s/AKfycbye0Ky4KMKw1O3oQj3ctxqpDPyIZu8PyEn8mt7pQOUiLkqvSZ4OUi-oshm2XEUs8PdMjw/exec", json=data)
    except Exception as e:
        print("❌ Google Script Error:", e)

# ✅ Send OTP
def send_otp(email):
    session.pop('otp', None)
    session.pop('otp_time', None)
    otp = str(random.randint(1000, 9999))
    session.update({'otp': otp, 'otp_time': time.time(), 'email': email, 'otp_attempts': 0})
    now = datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%d %B %Y, %I:%M %p")
    subject = f"🔐 Your OTP for JAIMIN's Login – {now}"
    msg = Message(subject=subject, recipients=[email], reply_to="noreply@example.com")
    msg.body = f"Your OTP is: {otp}"
    msg.html = f"""<!DOCTYPE html><html><head><style>
    body{{font-family:'Segoe UI';}} .otp-box{{font-size:24px;letter-spacing:6px;padding:10px;background:#222;color:#fff;}}
    </style></head><body><div><h2>🔐 JAIMIN PARMAR's Login OTP</h2>
    <p>Your OTP is:</p><div class="otp-box">{otp}</div><p>Valid for 5 minutes.</p></div></body></html>"""
    try:
        mail.send(msg)
        print(f"✅ OTP sent to {email}")
    except Exception as e:
        print("❌ OTP Email Failed:", e)

# ✅ Login Route
@app.route('/', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'): return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        if not email:
            return render_template('login.html', error="Enter a valid email.")
        session['email'] = email
        if session.get('verified') and session['email'] == email:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        send_otp(email)
        return redirect(url_for('verify'))
    return render_template('login.html')

# ✅ OTP Verification Route
@app.route('/verify', methods=['GET', 'POST'])
def verify():
    if session.get('logged_in'): return redirect(url_for('dashboard'))
    if request.method == 'POST':
        user_otp = request.form.get('otp', '').strip()
        otp_time = session.get('otp_time')
        if not session.get('otp') or time.time() - otp_time > 300:
            session.pop('otp', None)
            return render_template('verify.html', error="⏰ OTP expired.")
        if user_otp == session.get('otp'):
            session.update({
                'verified': True, 'logged_in': True,
                'login_time': datetime.now(pytz.timezone("Asia/Kolkata")),
                'ip': request.remote_addr, 'browser': request.user_agent.string
            })
            update_last_login(session['email'])
            send_to_google_script(session['email'], "Login")
            return redirect(url_for('dashboard'))
        return render_template('verify.html', error="❌ Invalid OTP")
    return render_template('verify.html')

# ✅ Dashboard Route
@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'): return redirect(url_for('login'))
    last_login = get_last_login(session['email'])
    return render_template('dashboard.html', email=session['email'], last_login=last_login)

# ✅ Logout Route
@app.route('/logout')
def logout():
    email = session.get('email', 'Unknown')
    session['login_time'] = datetime.now(pytz.timezone("Asia/Kolkata"))
    send_to_google_script(email, "Logout")
    session.clear()
    return redirect(url_for('login'))

# ✅ Maintenance Page
@app.route('/maintenance')
def maintenance():
    return render_template("maintenance.html"), 503

# ✅ Resend OTP
@app.route('/resend_otp', methods=['POST'])
def resend_otp():
    if 'email' not in session:
        return "Session expired", 401
    try:
        send_otp(session['email'])
        return "OTP Resent", 200
    except Exception as e:
        return f"Failed: {str(e)}", 500

# ✅ QR Code Generator
@app.route('/generate_qr', methods=['POST'])
def generate_qr():
    url = request.form.get('url')
    if not url:
        return "No URL provided", 400
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO(); img.save(buf); buf.seek(0)
    try:
        requests.post("https://script.google.com/macros/s/YOUR_SECOND_SCRIPT_ID/exec", json={"url": url, "ip": request.remote_addr})
    except Exception as e:
        print("QR log failed:", e)
    return send_file(buf, mimetype='image/png')

if __name__ == '__main__':
    app.run(debug=True)
