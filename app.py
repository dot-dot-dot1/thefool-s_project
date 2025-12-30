from flask import Flask, render_template
app = Flask(__name__)

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
    app.run(debug=True)



