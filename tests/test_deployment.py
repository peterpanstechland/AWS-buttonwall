import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wall_backend.__main__ import main
from wall_backend import server


class DeploymentTests(unittest.TestCase):
    def test_serial_mode_never_falls_back_to_demo(self):
        with patch.dict(os.environ, {"DEVICE_MODE": "serial"}, clear=True):
            with patch("wall_backend.__main__.serve") as serve:
                with self.assertRaisesRegex(SystemExit, "serial MCU transport"):
                    main()
                serve.assert_not_called()

    def test_unknown_mode_is_rejected(self):
        with patch.dict(os.environ, {"DEVICE_MODE": "typo"}, clear=True):
            with self.assertRaisesRegex(SystemExit, "Unsupported DEVICE_MODE"):
                main()

    def test_deployment_settings_reach_server(self):
        settings = {
            "DEVICE_MODE": "mock", "WALL_HOST": "0.0.0.0", "WALL_PORT": "8092",
            "WALL_DB_PATH": "/var/lib/aws-wall/wall.db",
        }
        with patch.dict(os.environ, settings, clear=True):
            with patch("wall_backend.__main__.serve") as serve:
                main()
                serve.assert_called_once_with(
                    host="0.0.0.0", port=8092, db_path="/var/lib/aws-wall/wall.db"
                )

    def test_database_persists_outside_release_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "persistent" / "wall.db"
            # Exercise startup twice without opening a socket or starting its timer thread.
            with patch.object(server, "ThreadingHTTPServer"), patch.object(server.threading, "Thread"):
                server.serve(db_path=database)
                server.ENGINE.store.conn.execute(
                    "INSERT INTO audit (at, action, detail) VALUES ('now', 'deployment', 'kept')"
                )
                server.ENGINE.store.conn.commit()
                server.ENGINE.store.conn.close()
                server.serve(db_path=database)
                try:
                    row = server.ENGINE.store.conn.execute(
                        "SELECT detail FROM audit WHERE action = 'deployment'"
                    ).fetchone()
                    self.assertEqual(row["detail"], "kept")
                finally:
                    server.ENGINE.store.conn.close()


if __name__ == "__main__":
    unittest.main()
