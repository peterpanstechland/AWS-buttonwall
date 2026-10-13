import os

from wall_backend.server import serve

if __name__ == "__main__":
    serve(port=int(os.environ.get("WALL_PORT", "8091")))
