import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from aiogram import executor

from bot_app import dp
from scheduler_jobs import on_shutdown_scheduler, on_startup_scheduler


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        return


def run_health_server():
    port = int(os.getenv("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()

    executor.start_polling(
        dp,
        skip_updates=True,
        on_startup=on_startup_scheduler,
        on_shutdown=on_shutdown_scheduler,
    )