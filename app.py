from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import yfinance as yf
from datetime import date, datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

app = Flask(__name__)
app.secret_key = "super_secret_key_change_this"

# EMAIL CONFIG — fill these in

GMAIL_ADDRESS = "your_gmail@gmail.com"
GMAIL_APP_PASSWORD = "your_app_password_here"  # Google App Password, not your real password



# DATABASE INITIALIZATION

def init_db():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS stocks (
        stock_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        ticker TEXT,
        shares REAL DEFAULT 0,
        purchase_price REAL DEFAULT 0,
        purchase_date TEXT DEFAULT '',
        display_order INTEGER DEFAULT 0,
        UNIQUE(user_id, ticker),
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )
    """)

    # ALERTS TABLE
    c.execute("""
    CREATE TABLE IF NOT EXISTS alerts_sent (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        ticker TEXT,
        alert_type TEXT,
        sent_date TEXT,
        UNIQUE(user_id, ticker, alert_type, sent_date)
    )
    """)

    # NOTIFICATIONS TABLE
    c.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        ticker TEXT,
        alert_type TEXT,
        change_pct REAL,
        value REAL,
        created_at TEXT,
        is_read INTEGER DEFAULT 0
    )
    """)

    # Migrate stocks table
    for col, definition in [
        ("purchase_price", "REAL DEFAULT 0"),
        ("purchase_date", "TEXT DEFAULT ''"),
        ("display_order", "INTEGER DEFAULT 0"),
    ]:
        try:
            c.execute(f"ALTER TABLE stocks ADD COLUMN {col} {definition}")
        except:
            pass

    # Migrate users table
    try:
        c.execute("ALTER TABLE users ADD COLUMN alert_threshold REAL DEFAULT 5.0")
    except:
        pass

    conn.commit()
    conn.close()


# EMAIL SENDER

def send_alert_email(to_email, username, ticker, alert_type, change_pct, value):
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Stock Alert: {ticker} moved {change_pct:+.2f}%"
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = to_email

        alert_label = "today" if alert_type == "daily" else "since you bought it"
        color = "#10b981" if change_pct >= 0 else "#ef4444"

        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:500px;margin:auto;padding:30px;background:#f4f6f9;border-radius:12px;">
          <h2 style="color:#1a1d23;">Stock Alert</h2>
          <p style="color:#6b7280;">Hi {username}, here is an update on your portfolio.</p>
          <div style="background:white;border-radius:10px;padding:20px;">
            <h3 style="margin:0 0 12px 0;">{ticker}</h3>
            <p>Has moved <strong style="color:{color};">{change_pct:+.2f}%</strong> {alert_label}</p>
            <p style="color:#6b7280;">Current position value: <strong>${value:,.2f}</strong></p>
          </div>
          <p style="font-size:12px;color:#9ca3af;text-align:center;margin-top:20px;">thefool portfolio tracker</p>
        </div>
        """

        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        print(f"[ALERT] Sent email to {to_email} for {ticker} ({alert_type}: {change_pct:+.2f}%)")
    except Exception as e:
        print(f"[ALERT ERROR] {e}")


# PRICE CHECKER (runs every 15 min)

def check_prices():
    now = datetime.now(pytz.timezone("America/New_York"))
    if now.weekday() > 4:
        return
    market_open  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    if not (market_open <= now <= market_close):
        return

    today = str(now.date())
    print(f"[SCHEDULER] Checking prices at {now.strftime('%H:%M ET')}")

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT user_id, username, email, alert_threshold FROM users")
    users = c.fetchall()

    for user_id, username, email, threshold in users:
        if not threshold or threshold <= 0:
            continue
        c.execute("SELECT ticker, shares, purchase_price FROM stocks WHERE user_id=?", (user_id,))
        stocks = c.fetchall()

        for ticker, shares, purchase_price in stocks:
            try:
                info = yf.Ticker(ticker).fast_info
                current_price = round(info.get("lastPrice", 0) or 0, 2)
                prev_close    = round(info.get("previousClose", current_price) or current_price, 2)
            except:
                continue
            if current_price == 0:
                continue

            value     = round(current_price * shares, 2)
            daily_pct = round(((current_price - prev_close) / prev_close * 100) if prev_close else 0, 2)
            cumul_pct = round(((current_price - purchase_price) / purchase_price * 100) if purchase_price else 0, 2)

            for alert_type, change_pct in [("daily", daily_pct), ("cumulative", cumul_pct)]:
                if abs(change_pct) >= threshold:
                    try:
                        c.execute(
                            "INSERT INTO alerts_sent (user_id, ticker, alert_type, sent_date) VALUES (?, ?, ?, ?)",
                            (user_id, ticker, alert_type, today)
                        )
                        conn.commit()
                        # Save to notifications table
                        c.execute(
                            """INSERT INTO notifications (user_id, ticker, alert_type, change_pct, value, created_at, is_read)
                            VALUES (?, ?, ?, ?, ?, ?, 0)""",
                            (user_id, ticker, alert_type, change_pct, value, now.strftime("%Y-%m-%d %H:%M"))
                        )
                        conn.commit()
                        send_alert_email(email, username, ticker, alert_type, change_pct, value)
                    except sqlite3.IntegrityError:
                        pass  # already sent today

    conn.close()


# HELPER: GET STOCK PRICES

def get_stock_prices(ticker):
    try:
        info = yf.Ticker(ticker).fast_info
        current = round(info.get("lastPrice", 0) or 0, 2)
        prev = round(info.get("previousClose", current) or current, 2)
        return current, prev
    except:
        return 0, 0


# HOME REDIRECT

@app.route("/")
def index():
    return redirect(url_for("login"))

# SIGNUP

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]

        # Basic email format validation
        import re
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            return render_template("signup.html", error="Please enter a valid email address.")

        hashed = generate_password_hash(password)

        conn = sqlite3.connect("database.db")
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                      (username, email, hashed))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return render_template("signup.html", error="Username or email already exists.")
        conn.close()
        return redirect(url_for("login"))

    return render_template("signup.html")


# LOGIN

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_input = request.form["login"]
        password = request.form["password"]

        conn = sqlite3.connect("database.db")
        c = conn.cursor()
        c.execute("""
            SELECT user_id, username, email, password_hash FROM users
            WHERE username=? OR email=?
        """, (login_input, login_input))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[3], password):
            session["user_id"] = user[0]
            session["username"] = user[1]
            return redirect(url_for("home"))

        return render_template("login.html", error="Incorrect username/email or password.")

    return render_template("login.html")


# HOME PAGE (PORTFOLIO)

@app.route("/home")
def home():
    if "user_id" not in session:
        return redirect(url_for("login"))

    sort_by = request.args.get("sort", "display_order")
    valid_sorts = ["display_order", "value", "daily_gain_pct", "cumulative_gain_pct", "ticker"]
    if sort_by not in valid_sorts:
        sort_by = "display_order"

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("""
        SELECT ticker, shares, purchase_price, purchase_date, display_order
        FROM stocks WHERE user_id=? ORDER BY display_order ASC
    """, (session["user_id"],))
    rows = c.fetchall()
    conn.close()

    stocks = []
    total_portfolio = 0
    total_book = 0
    total_daily_gain = 0

    for row in rows:
        ticker, shares, purchase_price, purchase_date, display_order = row
        current_price, prev_close = get_stock_prices(ticker)

        value = round(current_price * shares, 2)
        book_value = round(purchase_price * shares, 2)

        daily_gain_dollar = round((current_price - prev_close) * shares, 2)
        daily_gain_pct = round(((current_price - prev_close) / prev_close * 100) if prev_close else 0, 2)

        cumulative_gain_dollar = round((current_price - purchase_price) * shares, 2) if purchase_price else 0
        cumulative_gain_pct = round(((current_price - purchase_price) / purchase_price * 100) if purchase_price else 0, 2)

        total_portfolio += value
        total_book += book_value
        total_daily_gain += daily_gain_dollar

        stocks.append({
            "ticker": ticker,
            "shares": shares,
            "price": current_price,
            "value": value,
            "book_value": book_value,
            "purchase_price": purchase_price,
            "purchase_date": purchase_date,
            "display_order": display_order,
            "daily_gain_dollar": daily_gain_dollar,
            "daily_gain_pct": daily_gain_pct,
            "cumulative_gain_dollar": cumulative_gain_dollar,
            "cumulative_gain_pct": cumulative_gain_pct,
        })

    # Sort
    if sort_by == "value":
        stocks.sort(key=lambda x: x["value"], reverse=True)
    elif sort_by == "daily_gain_pct":
        stocks.sort(key=lambda x: x["daily_gain_pct"], reverse=True)
    elif sort_by == "cumulative_gain_pct":
        stocks.sort(key=lambda x: x["cumulative_gain_pct"], reverse=True)
    elif sort_by == "ticker":
        stocks.sort(key=lambda x: x["ticker"])

    total_cumulative_gain = round(total_portfolio - total_book, 2)
    total_cumulative_pct = round((total_cumulative_gain / total_book * 100) if total_book else 0, 2)
    total_daily_gain_pct = round((total_daily_gain / (total_portfolio - total_daily_gain) * 100) if (total_portfolio - total_daily_gain) else 0, 2)

    # Fetch alert threshold and notifications for this user
    conn2 = sqlite3.connect("database.db")
    c2 = conn2.cursor()
    c2.execute("SELECT alert_threshold FROM users WHERE user_id=?", (session["user_id"],))
    thresh_row = c2.fetchone()
    alert_threshold = thresh_row[0] if thresh_row else 5.0

    c2.execute("""
        SELECT id, ticker, alert_type, change_pct, value, created_at, is_read
        FROM notifications WHERE user_id=?
        ORDER BY created_at DESC LIMIT 20
    """, (session["user_id"],))
    notifications = [
        {"id": r[0], "ticker": r[1], "alert_type": r[2], "change_pct": r[3],
         "value": r[4], "created_at": r[5], "is_read": r[6]}
        for r in c2.fetchall()
    ]
    unread_count = sum(1 for n in notifications if not n["is_read"])
    conn2.close()

    return render_template(
        "home.html",
        username=session["username"],
        stocks=stocks,
        total_portfolio=round(total_portfolio, 2),
        total_book=round(total_book, 2),
        total_daily_gain=round(total_daily_gain, 2),
        total_daily_gain_pct=round(total_daily_gain_pct, 2),
        total_cumulative_gain=total_cumulative_gain,
        total_cumulative_pct=total_cumulative_pct,
        sort_by=sort_by,
        alert_threshold=alert_threshold,
        notifications=notifications,
        unread_count=unread_count
    )


# ADD STOCK

@app.route("/add_stock", methods=["POST"])
def add_stock():
    if "user_id" not in session:
        return redirect(url_for("login"))

    ticker = request.form["ticker"].upper()
    shares = float(request.form["shares"])
    purchase_date = request.form.get("purchase_date") or str(date.today())

    current_price, _ = get_stock_prices(ticker)
    if current_price == 0:
        return redirect(url_for("home", error="Invalid ticker symbol — please check and try again."))

    # Try to get historical price for the purchase date
    purchase_price = current_price
    if purchase_date != str(date.today()):
        try:
            from datetime import datetime, timedelta
            end_date = (datetime.strptime(purchase_date, "%Y-%m-%d") + timedelta(days=5)).strftime("%Y-%m-%d")
            hist = yf.Ticker(ticker).history(start=purchase_date, end=end_date)
            if not hist.empty:
                purchase_price = round(hist["Close"].iloc[0], 2)
        except:
            purchase_price = current_price

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT shares FROM stocks WHERE user_id=? AND ticker=?",
              (session["user_id"], ticker))
    existing = c.fetchone()

    if existing:
        new_shares = existing[0] + shares
        c.execute("""
            UPDATE stocks SET shares=?, purchase_price=?, purchase_date=?
            WHERE user_id=? AND ticker=?
        """, (new_shares, purchase_price, purchase_date, session["user_id"], ticker))
    else:
        c.execute("SELECT MAX(display_order) FROM stocks WHERE user_id=?", (session["user_id"],))
        max_order = c.fetchone()[0] or 0
        c.execute("""
            INSERT INTO stocks (user_id, ticker, shares, purchase_price, purchase_date, display_order)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session["user_id"], ticker, shares, purchase_price, purchase_date, max_order + 1))

    conn.commit()
    conn.close()
    return redirect(url_for("home"))

# REMOVE STOCK

@app.route("/remove_stock", methods=["POST"])
def remove_stock():
    if "user_id" not in session:
        return redirect(url_for("login"))

    ticker = request.form["ticker"]
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("DELETE FROM stocks WHERE user_id=? AND ticker=?", (session["user_id"], ticker))
    conn.commit()
    conn.close()
    return redirect(url_for("home"))



# EDIT STOCK

@app.route("/edit_stock", methods=["POST"])
def edit_stock():
    if "user_id" not in session:
        return redirect(url_for("login"))

    ticker = request.form["ticker"]
    shares = float(request.form["shares"])
    purchase_price = float(request.form["purchase_price"])
    purchase_date = request.form["purchase_date"]

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("""
        UPDATE stocks SET shares=?, purchase_price=?, purchase_date=?
        WHERE user_id=? AND ticker=?
    """, (shares, purchase_price, purchase_date, session["user_id"], ticker))
    conn.commit()
    conn.close()
    return redirect(url_for("home"))


# CHANGE USERNAME

@app.route("/change_username", methods=["POST"])
def change_username():
    if "user_id" not in session:
        return redirect(url_for("login"))

    new_username = request.form["new_username"].strip()
    password = request.form["password"]

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT password_hash FROM users WHERE user_id=?", (session["user_id"],))
    row = c.fetchone()

    if not row or not check_password_hash(row[0], password):
        conn.close()
        return redirect(url_for("home", error="Incorrect password."))

    try:
        c.execute("UPDATE users SET username=? WHERE user_id=?", (new_username, session["user_id"]))
        conn.commit()
        session["username"] = new_username
    except sqlite3.IntegrityError:
        conn.close()
        return redirect(url_for("home", error="That username is already taken."))

    conn.close()
    return redirect(url_for("home", success="Username updated successfully."))

# CHANGE PASSWORD

@app.route("/change_password", methods=["POST"])
def change_password():
    if "user_id" not in session:
        return redirect(url_for("login"))

    current_password = request.form["current_password"]
    new_password = request.form["new_password"]
    confirm_password = request.form["confirm_password"]

    if new_password != confirm_password:
        return redirect(url_for("home", error="New passwords do not match."))

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT password_hash FROM users WHERE user_id=?", (session["user_id"],))
    row = c.fetchone()

    if not row or not check_password_hash(row[0], current_password):
        conn.close()
        return redirect(url_for("home", error="Current password is incorrect."))

    new_hash = generate_password_hash(new_password)
    c.execute("UPDATE users SET password_hash=? WHERE user_id=?", (new_hash, session["user_id"]))
    conn.commit()
    conn.close()
    return redirect(url_for("home", success="Password changed successfully."))


# -------------------------
# DELETE ACCOUNT
# -------------------------
@app.route("/delete_account", methods=["POST"])
def delete_account():
    if "user_id" not in session:
        return redirect(url_for("login"))

    confirm_username = request.form["confirm_username"].strip()
    password = request.form["password"]

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT username, password_hash FROM users WHERE user_id=?", (session["user_id"],))
    row = c.fetchone()

    if not row or row[0] != confirm_username or not check_password_hash(row[1], password):
        conn.close()
        return redirect(url_for("home", error="Username or password incorrect. Account not deleted."))

    c.execute("DELETE FROM stocks WHERE user_id=?", (session["user_id"],))
    c.execute("DELETE FROM users WHERE user_id=?", (session["user_id"],))
    conn.commit()
    conn.close()
    session.clear()
    return redirect(url_for("login"))


# -------------------------
# SAVE DISPLAY ORDER
# -------------------------
@app.route("/save_order", methods=["POST"])
def save_order():
    if "user_id" not in session:
        return jsonify({"error": "not logged in"}), 401

    order = request.get_json().get("order", [])
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    for i, ticker in enumerate(order):
        c.execute("UPDATE stocks SET display_order=? WHERE user_id=? AND ticker=?",
                  (i, session["user_id"], ticker))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


# -------------------------
# STOCK DETAIL PAGE
# -------------------------
@app.route("/stock/<ticker>")
def stock_page(ticker):
    if "user_id" not in session:
        return redirect(url_for("login"))

    try:
        info = yf.Ticker(ticker).info
        current_price = info.get("regularMarketPrice") or 0
        name = info.get("longName") or ticker
        change = info.get("regularMarketChangePercent") or 0
        prev_close = info.get("regularMarketPreviousClose") or current_price
    except:
        current_price = 0
        name = ticker
        change = 0
        prev_close = 0

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT shares, purchase_price, purchase_date FROM stocks WHERE user_id=? AND ticker=?",
              (session["user_id"], ticker))
    row = c.fetchone()
    conn.close()

    shares = row[0] if row else 0
    purchase_price = row[1] if row else 0
    purchase_date = row[2] if row else ""

    value = round(shares * current_price, 2)
    book_value = round(shares * purchase_price, 2)

    daily_gain_dollar = round((current_price - prev_close) * shares, 2)
    daily_gain_pct = round(((current_price - prev_close) / prev_close * 100) if prev_close else 0, 2)
    cumulative_gain_dollar = round((current_price - purchase_price) * shares, 2) if purchase_price else 0
    cumulative_gain_pct = round(((current_price - purchase_price) / purchase_price * 100) if purchase_price else 0, 2)

    return render_template(
        "stock.html",
        ticker=ticker,
        name=name,
        price=round(current_price, 2),
        change=round(change, 2),
        shares=shares,
        value=value,
        book_value=book_value,
        purchase_price=purchase_price,
        purchase_date=purchase_date,
        daily_gain_dollar=daily_gain_dollar,
        daily_gain_pct=daily_gain_pct,
        cumulative_gain_dollar=cumulative_gain_dollar,
        cumulative_gain_pct=cumulative_gain_pct,
    )


# -------------------------
# STOCK HISTORY API
# -------------------------
@app.route("/stock_history/<ticker>")
def stock_history(ticker):
    if "user_id" not in session:
        return jsonify({"error": "not logged in"}), 401

    period = request.args.get("period", "1mo")
    if period not in ["1d", "1wk", "1mo", "3mo", "1y"]:
        period = "1mo"

    try:
        stock = yf.Ticker(ticker)
        if period == "1d":
            hist = stock.history(period="1d", interval="5m")
            labels = [d.strftime("%H:%M") for d in hist.index]
        else:
            hist = stock.history(period=period)
            labels = [str(d.date()) for d in hist.index]

        prices = [round(p, 2) for p in hist["Close"].tolist()]
        return jsonify({"labels": labels, "prices": prices})

    except Exception as e:
        print(e)
        return jsonify({"error": "Could not fetch history"}), 500


# -------------------------
# DASHBOARD
# -------------------------
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("dashboard.html")


# -------------------------
# LOGOUT
# -------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# -------------------------
# VIEW USERS (DEBUG PAGE)
# -------------------------
@app.route("/users")
def view_users():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT user_id, username, email FROM users")
    users = c.fetchall()
    conn.close()
    return render_template("users.html", users=users)


# -------------------------
# MARK NOTIFICATION READ
# -------------------------
@app.route("/mark_read/<int:notif_id>", methods=["POST"])
def mark_read(notif_id):
    if "user_id" not in session:
        return jsonify({"error": "not logged in"}), 401
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?", (notif_id, session["user_id"]))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


# -------------------------
# MARK ALL NOTIFICATIONS READ
# -------------------------
@app.route("/mark_all_read", methods=["POST"])
def mark_all_read():
    if "user_id" not in session:
        return jsonify({"error": "not logged in"}), 401
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (session["user_id"],))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/test_alert")
def test_alert():
    check_prices()
    return "Alert check ran — check your email and terminal."


# -------------------------
# UPDATE ALERT THRESHOLD
# -------------------------
@app.route("/update_threshold", methods=["POST"])
def update_threshold():
    if "user_id" not in session:
        return redirect(url_for("login"))

    try:
        threshold = float(request.form["alert_threshold"])
        if threshold < 0:
            raise ValueError
    except ValueError:
        return redirect(url_for("home", error="Invalid threshold value."))

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("UPDATE users SET alert_threshold=? WHERE user_id=?", (threshold, session["user_id"]))
    conn.commit()
    conn.close()
    session["alert_threshold"] = threshold
    return redirect(url_for("home", success=f"Alert threshold set to {threshold}%."))


# -------------------------
# RUN APP
# -------------------------
if __name__ == "__main__":
    init_db()

    # Start background price checker
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_prices, "interval", minutes=15, id="price_check")
    scheduler.start()
    print("[SCHEDULER] Price alert checker started — runs every 15 minutes during market hours.")

    try:
        app.run(debug=True, use_reloader=False)  # use_reloader=False prevents scheduler from doubling up
    finally:
        scheduler.shutdown()
