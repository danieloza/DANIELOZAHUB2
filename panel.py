# -*- coding: utf-8 -*-
from datetime import datetime

from flask import Flask, render_template_string

from domain.metrics import summarize_24h
from storage_router import retry_stats

app = Flask(__name__)

HTML = """
<!doctype html><title>Danex Dashboard</title>
<style>
:root{--bg:#f5f7fb;--card:#ffffff;--ink:#1e2b3a;--muted:#5b6b7b;--line:#d8e0ea;--ok:#2e7d32;--warn:#f9a825;--bad:#c62828}
body{font-family:Segoe UI,Arial,sans-serif;background:var(--bg);color:var(--ink);margin:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
.k{font-size:12px;color:var(--muted)}
.v{font-size:26px;font-weight:700;margin-top:6px}
.ok{color:var(--ok)} .warn{color:var(--warn)} .bad{color:var(--bad)}
</style>
<h2>Danex Dashboard</h2>
<p>Aktualizacja: {{ts}}</p>
<div class="grid">
  <div class="card"><div class="k">OCR Success Rate (24h)</div><div class="v {{'ok' if m.ocr_success_rate >= 95 else 'warn'}}">{{m.ocr_success_rate}}%</div></div>
  <div class="card"><div class="k">OCR p95 latency</div><div class="v">{{m.ocr_latency_p95_ms}} ms</div></div>
  <div class="card"><div class="k">Errors 24h</div><div class="v {{'bad' if m.errors_24h > 0 else 'ok'}}">{{m.errors_24h}}</div></div>
  <div class="card"><div class="k">Retry Queue</div><div class="v {{'warn' if q.queue > 0 else 'ok'}}">{{q.queue}}</div></div>
  <div class="card"><div class="k">Dead Letter</div><div class="v {{'bad' if q.dlq > 0 else 'ok'}}">{{q.dlq}}</div></div>
  <div class="card"><div class="k">Events 24h</div><div class="v">{{m.events_24h}}</div></div>
</div>
"""


@app.get("/")
def home():
    m = summarize_24h()
    q = retry_stats()
    return render_template_string(HTML, m=m, q=q, ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
