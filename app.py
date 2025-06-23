from flask import Flask, request, jsonify, send_from_directory, render_template
import os
from comicai import run_comicai_direct

app = Flask(__name__, static_folder="static", template_folder="templates")
COMIC_DIR = os.path.join("static", "generated_comics")
os.makedirs(COMIC_DIR, exist_ok=True)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/generate", methods=["POST"])
def generate_comic():
    try:
        data = request.json
        product = data["product"]
        audience = data.get("audience", "general")
        num_panels = int(data.get("num_panels", 4))

        output_path = run_comicai_direct(product, audience, num_panels, COMIC_DIR)

        return jsonify({
            "success": True,
            "comic_url": f"/static/generated_comics/{os.path.basename(output_path)}"
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
