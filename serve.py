"""Serve the charter workflow dashboard on localhost using only Python."""

import argparse
import json
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


class Dashboard(BaseHTTPRequestHandler):
    def send_body(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, payload):
        self.send_body(status, "application/json", json.dumps(payload).encode("utf-8"))

    def is_local_request(self):
        port = self.server.server_port
        return self.headers.get("Host") in {f"localhost:{port}", f"127.0.0.1:{port}"}

    def checkpoint(self, request_id):
        if not isinstance(request_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", request_id
        ):
            raise ValueError("Enter a valid request ID.")
        return self.server.state_dir / f"{request_id}.json"

    def do_GET(self):
        if not self.is_local_request():
            self.send_json(403, {"error": "Use the local dashboard address."})
            return
        url = urlsplit(self.path)
        if url.path in ASSETS:
            filename, content_type = ASSETS[url.path]
            self.send_body(200, content_type, (ROOT / "web" / filename).read_bytes())
            return
        if url.path != "/api/workflow":
            self.send_json(404, {"error": "Page not found."})
            return
        request_id = parse_qs(url.query).get("id", [""])[0]
        try:
            state = json.loads(self.checkpoint(request_id).read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.send_json(404, {"error": "That request is not in this workspace."})
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except OSError:
            self.send_json(500, {"error": "Could not read the saved workflow."})
        else:
            self.send_json(200, {"state": state})

    def do_POST(self):
        port = self.server.server_port
        origin = self.headers.get("Origin")
        if not self.is_local_request() or (
            origin and origin not in {f"http://localhost:{port}", f"http://127.0.0.1:{port}"}
        ):
            self.send_json(403, {"error": "Use the local dashboard address."})
            return
        if self.path not in {"/api/start", "/api/approve"}:
            self.send_json(404, {"error": "Action not found."})
            return
        if self.headers.get_content_type() != "application/json":
            self.send_json(415, {"error": "Expected a JSON request."})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                raise ValueError("Invalid request size.")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object.")
            if self.path == "/api/start":
                request_id = f"REQ-{uuid4().hex[:8].upper()}"
                self.run_command("start", request_id)
            else:
                request_id = data.get("id")
                if not self.checkpoint(request_id).is_file():
                    self.send_json(404, {"error": "That request is not in this workspace."})
                    return
                decision = data.get("decision")
                if decision not in ("approve", "withhold"):
                    raise ValueError("Choose approve or withhold.")
                self.run_command("approve", request_id, "APPROVE\n" if decision == "approve" else "no\n")
        except (ValueError, TypeError) as error:
            self.send_json(400, {"error": str(error)})
        except (OSError, subprocess.TimeoutExpired):
            self.send_json(500, {"error": "Could not run the workflow command. Reload to check its state."})

    def run_command(self, command, request_id, response=""):
        path = self.checkpoint(request_id)
        result = subprocess.run(
            [
                sys.executable, str(ROOT / "charter.py"),
                "--state-dir", str(self.server.state_dir), command, request_id,
            ],
            input=response, text=True, capture_output=True, timeout=10, check=False,
        )
        if not path.is_file():
            self.send_json(500, {"error": result.stdout.strip() or "The workflow could not save its state."})
            return
        state = json.loads(path.read_text(encoding="utf-8"))
        output = result.stdout.strip()
        if result.returncode and state["status"] != "FAILED":
            self.send_json(409, {"state": state, "error": output or "The action could not run."})
            return
        self.send_json(200, {"state": state, "output": output})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--state-dir", type=Path, default=Path(".charter-state"))
    args = parser.parse_args()
    with HTTPServer(("127.0.0.1", args.port), Dashboard) as server:
        server.state_dir = args.state_dir.resolve()
        print(f"Charter dashboard: http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
