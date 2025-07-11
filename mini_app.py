from flask import Flask, request
app = Flask(__name__)

@app.route("/callback", methods=["POST"])
def callback():
    print("受信:", request.data)
    return "OK"

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000) 