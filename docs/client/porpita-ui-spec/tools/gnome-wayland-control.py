"""Drive and capture the isolated GNOME Shell Wayland acceptance display."""

import json
import os
from pathlib import Path
import socket
import socketserver
import subprocess
import sys
import time

from gi.repository import Gio, GLib

KEYS = {
    "Escape": 1, "BackSpace": 14, "Tab": 15, "t": 20, "Return": 28, "ctrl": 29, "a": 30,
    "v": 47, "shift": 42, "alt": 56, "space": 57, "KP_Enter": 96, "Up": 103,
    "Left": 105, "Right": 106, "Down": 108, "super": 125, "0": 11,
}
RD = "org.gnome.Mutter.RemoteDesktop"
SC = "org.gnome.Mutter.ScreenCast"
DISPLAY_CONFIG = "org.gnome.Mutter.DisplayConfig"


def proxy(connection, name, path=None, interface=None):
    return Gio.DBusProxy.new_sync(
        connection, Gio.DBusProxyFlags.NONE, None, name,
        path or "/" + name.replace(".", "/"), interface or name, None,
    )


def call(target, name, args=None):
    return target.call_sync(name, args, Gio.DBusCallFlags.NONE, 5000, None).unpack()


class MutterSession:
    def __init__(self):
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        monitors = call(proxy(connection, DISPLAY_CONFIG), "GetCurrentState")[1]
        if len(monitors) != 1:
            raise RuntimeError("Expected one monitor on the isolated compositor")
        connector = monitors[0][0][0]
        remote_path, = call(proxy(connection, RD), "CreateSession")
        self.remote = proxy(connection, RD, remote_path, RD + ".Session")
        session_id = self.remote.get_cached_property("SessionId")
        screen_path, = call(proxy(connection, SC), "CreateSession", GLib.Variant(
            "(a{sv})", ({"remote-desktop-session-id": session_id},)
        ))
        screen = proxy(connection, SC, screen_path, SC + ".Session")
        stream_path, = call(screen, "RecordMonitor", GLib.Variant(
            "(sa{sv})", (connector, {"cursor-mode": GLib.Variant("u", 0)})
        ))
        self.node_id = None
        connection.signal_subscribe(
            SC, SC + ".Stream", "PipeWireStreamAdded", stream_path, None,
            Gio.DBusSignalFlags.NONE, self._stream_ready,
        )
        call(self.remote, "Start")
        context = GLib.MainContext.default()
        deadline = time.monotonic() + 12
        while self.node_id is None and time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            time.sleep(0.02)
        if self.node_id is None:
            raise RuntimeError("Mutter did not publish the PipeWire stream")

    def _stream_ready(self, _connection, _sender, _path, _interface, _signal, params):
        self.node_id, = params.unpack()

    def press(self, combination):
        codes = [KEYS[part] for part in combination.split("+")]
        held = []
        try:
            for code in codes:
                call(self.remote, "NotifyKeyboardKeycode", GLib.Variant("(ub)", (code, True)))
                held.append(code)
                time.sleep(0.035)
            time.sleep(0.18 if combination == "super+Tab" else 0.05)
        finally:
            for code in reversed(held):
                call(self.remote, "NotifyKeyboardKeycode", GLib.Variant("(ub)", (code, False)))
                time.sleep(0.02)

    def screenshot(self, filename):
        subprocess.run([
            "gst-launch-1.0", "-q", "pipewiresrc", f"path={self.node_id}", "num-buffers=1",
            "!", "videoconvert", "!", "pngenc", "snapshot=true", "!", "filesink",
            "location=" + str(filename),
        ], timeout=12, check=True, capture_output=True)


def serve(run, socket_path):
    session = MutterSession()

    class Request(socketserver.StreamRequestHandler):
        def handle(self):
            try:
                operation, value = json.loads(self.rfile.readline(4096))
                if operation == "key":
                    session.press(value)
                elif operation == "screenshot":
                    filename = Path(value).resolve()
                    if filename.parent != run / "evidence" or filename.suffix != ".png":
                        raise ValueError("Screenshot must be a PNG in the isolated evidence directory")
                    session.screenshot(filename)
                else:
                    raise ValueError("Unknown operation")
                reply = {"ok": True}
            except (KeyError, ValueError, GLib.Error, subprocess.SubprocessError) as error:
                reply = {"ok": False, "error": str(error)}
            self.wfile.write(json.dumps(reply).encode() + b"\n")

    with socketserver.UnixStreamServer(str(socket_path), Request) as server:
        server.serve_forever()


def main():
    run = Path(os.environ["PORPITA_NATIVE_RUN"]).resolve()
    runtime = Path(os.environ["XDG_RUNTIME_DIR"]).resolve()
    if runtime != run / "runtime" or os.environ.get("DISPLAY") or os.environ.get("HOME") != str(run / "home"):
        raise SystemExit("Expected an isolated Wayland validation session")
    os.umask(0o077)
    socket_path = runtime / "mutter-observer.sock"
    if sys.argv[1:] == ["serve"]:
        serve(run, socket_path)
        return
    operation, value = sys.argv[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(14)
        client.connect(str(socket_path))
        client.sendall(json.dumps([operation, value]).encode() + b"\n")
        with client.makefile("rb") as response:
            result = json.load(response)
    if not result["ok"]:
        raise SystemExit(result["error"])


if __name__ == "__main__":
    main()
