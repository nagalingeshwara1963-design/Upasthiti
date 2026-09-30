import os
import re

with open('app/web/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

with open('app/web/static/css/style.css', 'r', encoding='utf-8') as f:
    css = f.read()

with open('app/web/static/js/app.js', 'r', encoding='utf-8') as f:
    js = f.read()

# Make JS use API_BASE
js = "const API_BASE = window.location.hostname.includes('github.io') ? 'https://upasthiti-app.onrender.com' : '';\n" + js
js = js.replace('fetch("/api/', 'fetch(API_BASE + "/api/')
js = js.replace('fetch(`/api/', 'fetch(`${API_BASE}/api/')

html = html.replace('<link rel="stylesheet" href="/static/css/style.css">', f"<style>\n{css}\n</style>")
html = html.replace('<script src="/static/js/app.js"></script>', f"<script>\n{js}\n</script>")

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("index.html successfully updated to match desktop parity.")
