"""Public read-only server for generated HTML reports only."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os

report_dir = os.path.join(os.path.dirname(__file__), "data", "reports")
os.makedirs(report_dir, exist_ok=True)
os.chdir(report_dir)
server = ThreadingHTTPServer(("127.0.0.1", 8091), SimpleHTTPRequestHandler)
server.serve_forever()
