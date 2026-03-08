from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import yfinance as yf

app = Flask(__name__)
app.secret_key = "super_secret_key_change_this"


# -------------------------
# DATABASE INITIALIZATION
# -------------------------
def init_db():

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    # USERS TABLE
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL
    )
    """)

    # STOCKS TABLE
    c.execute("""
    CREATE TABLE IF NOT EXISTS stocks (
        stock_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        ticker TEXT,
        shares INTEGER DEFAULT 0,
        UNIQUE(user_id, ticker),
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )
    """)

    conn.commit()
    conn.close()


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

        hashed_password = generate_password_hash(password)

        conn = sqlite3.connect("database.db")
        c = conn.cursor()

        try:

            c.execute("""
            INSERT INTO users (username, email, password_hash)
            VALUES (?, ?, ?)
            """, (username, email, hashed_password))

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
        SELECT user_id, username, email, password_hash
        FROM users
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

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute(
        "SELECT ticker, shares FROM stocks WHERE user_id=?",
        (session["user_id"],)
    )

    rows = c.fetchall()
    conn.close()

    stocks = []
    total_portfolio = 0

    for row in rows:

        ticker = row[0]
        shares = row[1]

        try:

            stock = yf.Ticker(ticker)

            price = stock.fast_info.get("lastPrice", 0)

        except Exception as e:

            print(e)
            price = 0

        price = round(price, 2)

        value = round(price * shares, 2)

        total_portfolio += value

        stocks.append({
            "ticker": ticker,
            "shares": shares,
            "price": price,
            "value": value
        })

    return render_template(
        "home.html",
        username=session["username"],
        stocks=stocks,
        total_portfolio=round(total_portfolio, 2)
    )


# -------------------------
# ADD STOCK
# -------------------------
@app.route("/add_stock", methods=["POST"])
def add_stock():

    if "user_id" not in session:
        return redirect(url_for("login"))

    ticker = request.form["ticker"].upper()
    shares = int(request.form["shares"])

    try:

        stock = yf.Ticker(ticker)

        price = stock.fast_info.get("lastPrice")

        if price is None:
            return "Invalid ticker symbol"

    except Exception as e:

        print(e)
        return "Invalid ticker symbol"

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute(
        "SELECT shares FROM stocks WHERE user_id=? AND ticker=?",
        (session["user_id"], ticker)
    )

    existing = c.fetchone()

    if existing:

        new_shares = existing[0] + shares

        c.execute(
            "UPDATE stocks SET shares=? WHERE user_id=? AND ticker=?",
            (new_shares, session["user_id"], ticker)
        )

    else:

        c.execute(
            "INSERT INTO stocks (user_id, ticker, shares) VALUES (?, ?, ?)",
            (session["user_id"], ticker, shares)
        )

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

    c.execute(
        "DELETE FROM stocks WHERE user_id=? AND ticker=?",
        (session["user_id"], ticker)
    )

    conn.commit()
    conn.close()

    return redirect(url_for("home"))


# -------------------------
# STOCK DETAIL PAGE
# -------------------------
@app.route("/stock/<ticker>")
def stock_page(ticker):

    if "user_id" not in session:
        return redirect(url_for("login"))

    stock = yf.Ticker(ticker)

    try:

        info = stock.info

        price = info.get("regularMarketPrice") or 0
        name = info.get("longName") or ticker
        change = info.get("regularMarketChangePercent") or 0

    except Exception as e:

        print(e)

        price = 0
        name = ticker
        change = 0

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute(
        "SELECT shares FROM stocks WHERE user_id=? AND ticker=?",
        (session["user_id"], ticker)
    )

    row = c.fetchone()

    conn.close()

    shares = row[0] if row else 0

    value = round(shares * price, 2)

    return render_template(
        "stock.html",
        ticker=ticker,
        name=name,
        price=round(price, 2),
        change=round(change, 2),
        shares=shares,
        value=value
    )


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