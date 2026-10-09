"""Child process for the engine host.

The server starts ``python -m fizgig.web.engine_worker``. One process holds at
most one engine and the GPU lock.
"""
from fizgig.web.engine_host import worker_main


def main() -> None:
    # Import registers each tool's factory in this process.
    import fizgig.web.explorer
    import fizgig.web.refmod
    import fizgig.web.royale
    worker_main()


if __name__ == "__main__":
    main()
