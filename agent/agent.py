"""Worker server entrypoint for the Cozmo voice agent."""

from app.job import run_worker


def main() -> None:
    run_worker()


if __name__ == "__main__":
    main()
