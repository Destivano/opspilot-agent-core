"""Regression: a blocked console must not prevent local HTTP responses."""

import importlib.util
import io
from pathlib import Path
from unittest.mock import patch


def test_http_response_does_not_write_to_console():
    import app

    original_service = app.service
    original_principal = app.principal
    spec = importlib.util.spec_from_file_location(
        "local_demo_regression", Path(__file__).resolve().parents[1] / "scripts" / "local_demo.py"
    )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        request = b"GET /config HTTP/1.0\r\nHost: 127.0.0.1:8080\r\n\r\n"

        class Connection:
            def __init__(self):
                self.response = bytearray()

            def makefile(self, *args):
                return io.BytesIO(request)

            def settimeout(self, timeout):
                pass

            def sendall(self, data):
                self.response.extend(data)

        class UnavailableConsole:
            def write(self, value):
                raise AssertionError("HTTP handling must not write to the console")

        connection = Connection()
        with patch("sys.stderr", UnavailableConsole()):
            module.Handler(connection, ("127.0.0.1", 12345), object())
        response = bytes(connection.response)
        assert response.startswith(b"HTTP/1.0 200")
        assert b"Content-Length:" in response
        assert b'"localDemo": true' in response
    finally:
        app.service = original_service
        app.principal = original_principal
