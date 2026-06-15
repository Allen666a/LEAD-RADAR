from __future__ import annotations

import argparse

from app.services.agent_queue import run_worker_loop


def main() -> None:
    parser = argparse.ArgumentParser(prog="lead-radar-agent-worker")
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--poll", default=5, type=int)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    run_worker_loop(args.worker_id, poll_seconds=args.poll, once=args.once)


if __name__ == "__main__":
    main()
