#!/usr/bin/env python3
"""Device-ownership lock: contention, takeover by SIGTERM, release after a
killed holder, and the GUI release message. No hardware required."""
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import devlock

HOLDER = r"""
import os, signal, sys, time
sys.path.insert(0, %r)
import devlock
signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
lock = devlock.DeviceLock(sys.argv[1], mode="test")
assert lock.acquire(takeover=False)
print("held", flush=True)
time.sleep(30)
""" % ROOT


class TestDevLock(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="kbdrgb-lock-")
        os.environ["KEYBOARDRGB_RUNTIME_DIR"] = self.dir
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()
            p.stdout.close()

    def _holder(self, kind="runner"):
        p = subprocess.Popen([sys.executable, "-c", HOLDER, kind],
                             stdout=subprocess.PIPE, text=True, env=os.environ.copy())
        self.procs.append(p)
        self.assertEqual(p.stdout.readline().strip(), "held")
        return p

    def test_free_by_default(self):
        self.assertIsNone(devlock.owner())
        lock = devlock.DeviceLock("cli", mode="color")
        self.assertTrue(lock.try_acquire())
        rec = devlock.owner()
        self.assertEqual((rec["pid"], rec["kind"], rec["mode"]), (os.getpid(), "cli", "color"))
        lock.release()
        self.assertIsNone(devlock.owner())

    def test_contention_and_takeover(self):
        p = self._holder()
        self.assertEqual(devlock.owner()["pid"], p.pid)
        lock = devlock.DeviceLock("cli")
        self.assertFalse(lock.try_acquire())
        self.assertTrue(lock.acquire(takeover=True, timeout=3.0))
        self.assertEqual(p.wait(timeout=3), 0)  # exited through its SIGTERM handler
        lock.release()

    def test_killed_holder_releases(self):
        p = self._holder()
        p.send_signal(signal.SIGKILL)
        p.wait()
        self.assertIsNone(devlock.owner())

    def test_gui_release_message(self):
        gui_lock = devlock.DeviceLock("gui", mode="preview")
        self.assertTrue(gui_lock.try_acquire())
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(devlock.gui_socket_path())
        srv.listen(1)
        got = []

        def serve():
            conn, _ = srv.accept()
            line = conn.makefile().readline()
            got.append(json.loads(line))
            gui_lock.release()
            conn.sendall(b'{"ok": true}\n')
            conn.close()

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        self.assertTrue(devlock.request_release(timeout=2.0))
        t.join(2)
        srv.close()
        self.assertEqual(got, [{"cmd": "release"}])
        self.assertIsNone(devlock.owner())


if __name__ == "__main__":
    unittest.main()
