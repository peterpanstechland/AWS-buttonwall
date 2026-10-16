import os

from wall_backend.server import serve


def main():
    device_mode = os.environ.get("DEVICE_MODE", "mock").strip().lower()
    if device_mode not in {"mock", "bw_serial"}:
        raise SystemExit(
            f"Unsupported DEVICE_MODE={device_mode!r}: only 'mock' is implemented. "
            "The serial MCU transport is not available; refusing to start a simulated game."
        )
    options = {}
    if device_mode == "bw_serial":
        path = os.environ.get("WALL_SERIAL_PORT", "").strip()
        if not path:
            raise SystemExit("WALL_SERIAL_PORT is required for bw_serial")
        options["serial_path"] = path
    serve(
        host=os.environ.get("WALL_HOST", "127.0.0.1"),
        port=int(os.environ.get("WALL_PORT", "8091")),
        db_path=os.environ.get("WALL_DB_PATH") or None,
        **options,
    )


if __name__ == "__main__":
    main()
