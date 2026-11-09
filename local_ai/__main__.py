from __future__ import annotations

import argparse
import socket
_old_getaddrinfo = socket.getaddrinfo
def _ipv4_getaddrinfo(*args, **kwargs):
    responses = _old_getaddrinfo(*args, **kwargs)
    return [r for r in responses if r[0] == socket.AF_INET]
socket.getaddrinfo = _ipv4_getaddrinfo

from .config import Settings
from .http_api import serve


def main() -> None:
    defaults = Settings.from_env()
    parser = argparse.ArgumentParser(description="API local de IA do projeto IC")
    parser.add_argument("--host", default=defaults.host)
    parser.add_argument("--port", type=int, default=defaults.port)
    args = parser.parse_args()
    serve(defaults.with_network(host=args.host, port=args.port))


if __name__ == "__main__":
    main()

