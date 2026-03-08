from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import yfinance as yf
from datetime import date

app = Flask(__name__)
app.secret_key = "super_secret_key_change_this"


# -------------------------
# DATABASE INITIALIZATION
# -------------------------
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

    # Migrate existing tables safely
    for col, definition in [
        ("purchase_price", "REAL DEFAULT 0"),
        ("purchase_date", "TEXT DEFAULT ''"),
        ("display_order", "INTEGER DEFAULT 0"),
    ]:
        try:
            c.execute(f"ALTER TABLE stocks ADD COLUMN {col} {definition}")
        except:
            pass

    conn.commit()
    conn.close()


# -------------------------
# HELPER: GET STOCK PRICES
# -------------------------
def get_stock_prices(ticker):
    try:
        info = yf.Ticker(ticker).fast_info
        current = round(info.get("lastPrice", 0) or 0, 2)
        prev = round(info.get("previousClose", current) or current, 2)
        return current, prev
    except:
        return 0, 0


# -------------------------
# HOME REDIRECT
# -------------------------
@app.route("/")
def index():
    return redirect(url_for("login"))


# -------------------------
# SIGNUP
# -------------------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]
        hashed = generate_password_hash(password)

        conn = sqlite3.connect("database.db")
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                      (username, email, hashed))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return "Username or email already exists."
        conn.close()
        return redirect(url_for("login"))

    return render_template("signup.html")


# -------------------------
# LOGIN
# -------------------------
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

        return "Invalid credentials"

    return render_template("login.html")


# -------------------------
# HOME PAGE (PORTFOLIO)
# -------------------------
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
        sort_by=sort_by
    )


# -------------------------
# ADD STOCK
# -------------------------
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


# -------------------------
# REMOVE STOCK
# -------------------------
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


# -------------------------
# EDIT STOCK
# -------------------------
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
# RUN APP
# -------------------------
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
