"""Start a local-only HTTP service with a headed browser and Xvfb."""
from __future__ import annotations

import argparse


def main():
    parser = argparse.ArgumentParser(prog="job-platform-server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    import uvicorn
    from job_platforms.http_api import create_app
    uvicorn.run(
        create_app(),
        host=args.host,
        port=args.port,
        access_log=False,  # Query parameters may contain confidential values.
        log_level="warning",
    )


if __name__ == "__main__":
    main()
