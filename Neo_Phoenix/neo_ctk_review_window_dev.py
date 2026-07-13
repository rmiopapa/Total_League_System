from __future__ import annotations

from neo_ctk_review_window import NeoPhoenixCTkWindow


def main() -> int:
    NeoPhoenixCTkWindow(developer_mode=True).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
