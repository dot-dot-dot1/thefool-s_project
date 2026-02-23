from flask import Flask, render_template
import init_db

app = Flask(__name__)

def init_db():
    conn = sqlite.connect("database.db")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS Users(
        userID INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        password TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE CHECK (email LIKE '%@%.%') 
        )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS stocks (
        stock_id INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_name TEXT NOT NULL,
        stock_price REAL NOT NULL,
        stock_quantity INTEGER NOT NULL,
        purchase_date TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )
""")

@app.route("/") #Used to redicrect user to login page when using website
def home():
    return redicrect(url_for("login"))

# LOGIN
@app.route("/login", methods=["GET", "POST"]) #Offers 2 login methods
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        # Later: check database
        print(email, password)

        return "Login received"

    return render_template("login.html")

# SIGN UP
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        # Later: save to database
        print(email, password)

        return "Signup received"

    return render_template("signup.html")

if __name__ == "__main__":
    init_db.initialize_db
    app.run(debug=True)



