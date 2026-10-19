"""Local live viewer: http://127.0.0.1:8765 shows data/cad/robot/robot.glb and reloads it after every build."""

import http.server
import json
from functools import partial
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / "data" / "cad" / "robot"


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        path = path.split("?")[0]
        if path.startswith("/data/"):
            return str(DATA / path[len("/data/"):])
        return super().translate_path(path)

    def do_GET(self):
        if self.path.startswith("/version"):
            glb = DATA / "robot.glb"
            body = json.dumps({"glb": glb.stat().st_mtime if glb.exists() else 0}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass


def main(port=8765):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(HERE / "viewer")))
    print(f"viewer on http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
