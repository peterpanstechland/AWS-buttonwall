import os

from wall_backend.server import serve


def main():
    device_mode = os.environ.get("DEVICE_MODE", "mock").strip().lower()
    if device_mode != "mock":
        raise SystemExit(
            f"Unsupported DEVICE_MODE={device_mode!r}: only 'mock' is implemented. "
            "The serial MCU transport is not available; refusing to start a simulated game."
        )
    serve(
        host=os.environ.get("WALL_HOST", "127.0.0.1"),
        port=int(os.environ.get("WALL_PORT", "8091")),
        db_path=os.environ.get("WALL_DB_PATH") or None,
    )


if __name__ == "__main__":
    main()
