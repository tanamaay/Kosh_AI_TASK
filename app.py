import os

import pandas as pd
from flask import Flask, render_template, request

from reconciliation import process_statement, process_settlement, reconcile

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/")
def home():
    return render_template("upload.html")

@app.route("/process", methods=["POST"])
def process():
    stmt_file = request.files["statement"]
    sett_file = request.files["settlement"]

    stmt_path = os.path.join(UPLOAD_FOLDER, stmt_file.filename)
    sett_path = os.path.join(UPLOAD_FOLDER, sett_file.filename)

    stmt_file.save(stmt_path)
    sett_file.save(sett_path)

    stmt_df = process_statement(stmt_path)
    sett_df = process_settlement(sett_path)
    
    result = reconcile(stmt_df, sett_df)

    # Display formatting
    result["AmountVariance"] = result["AmountVariance"].apply(
        lambda x: f"{float(x):.6f}" if pd.notna(x) else "<NA>"
    )

    # Keep only required columns
    table = result[
        ["PartnerPin", "Classification", "FinalReconcileStatus", "AmountVariance"]
    ].to_html(index=False, classes="table table-striped", table_id="results-table")

    return render_template("results.html", table=table)


if __name__ == "__main__":
    # Render/Railway/Heroku-style platforms provide PORT
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
