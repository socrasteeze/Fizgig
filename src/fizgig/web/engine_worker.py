"""Child process for the engine host.

The server starts ``python -m fizgig.web.engine_worker``. One process holds at
most one engine and the GPU lock.
"""
from fizgig.web.engine_host import worker_main


def main() -> None:
    worker_main()


if __name__ == "__main__":
    main()
