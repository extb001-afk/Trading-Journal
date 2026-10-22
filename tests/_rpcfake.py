import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DOWN = object()


class Node:
    def __init__(self, fn):
        self.fn = fn
        self.calls = []
        self.lock = threading.Lock()
        nd = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"null")
                items = body if isinstance(body, list) else [body]
                out = []
                for it in items:
                    with nd.lock:
                        nd.calls.append((it.get("method"), it.get("params")))
                    try:
                        r = nd.fn(it.get("method"), it.get("params"))
                    except Exception as e:   # noqa: BLE001
                        out.append({"jsonrpc": "2.0", "id": it.get("id"), "error": {"code": 3, "message": "execution reverted: " + str(e)}})
                        continue
                    if r is DOWN:
                        self.send_response(500)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    out.append({"jsonrpc": "2.0", "id": it.get("id"), "result": r})
                b = json.dumps(out if isinstance(body, list) else out[0]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/rpc"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def loop_open(bf_engine, T):
    import _tronfake
    _tronfake.install_loop_open(bf_engine, T)
