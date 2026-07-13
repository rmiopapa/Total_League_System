from __future__ import annotations

from neo_review_window import NeoPhoenixReviewWindow


def main() -> int:
    NeoPhoenixReviewWindow(developer_mode=True).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
