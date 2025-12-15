from flask import Flask, render_template
app = Flask(__name__)

@app.route("/")
def index():
    return "Welcome to our Flask Web Application"

if __name__ == "__main__":
    app.run(debug=True)
