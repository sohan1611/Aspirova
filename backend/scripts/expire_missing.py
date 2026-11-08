"""Mark active opportunities closed when proven absent from freshly crawled boards."""

from sqlalchemy.orm import Session

from core.db import make_engine
from pipeline.expire import expire_missing_opportunities
from pipeline.retirement import retire_dead_board_listings, retire_rolling_window_listings


def main() -> None:
    engine = make_engine()
    with Session(engine) as session:
        closed_count = expire_missing_opportunities(session)
        dead_counts = retire_dead_board_listings(session)
        rolling_counts = retire_rolling_window_listings(session)
        session.commit()
        print(f"opportunities marked closed: {closed_count}", flush=True)
        for board, count in dead_counts.items():
            print(f"dead board {board}: closed={count}", flush=True)
        for source, count in rolling_counts.items():
            print(f"rolling-window TTL {source}: closed={count}", flush=True)


if __name__ == "__main__":
    main()
