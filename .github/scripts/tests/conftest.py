import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


@pytest.fixture
def http_files(tmp_path):
    directory = tmp_path / "http"
    directory.mkdir()
    handler = lambda *args, **kwargs: QuietHandler(  # noqa: E731
        *args, directory=str(directory), **kwargs
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield directory, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()