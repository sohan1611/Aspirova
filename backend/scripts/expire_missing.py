"""Mark active opportunities closed when proven absent from freshly crawled boards."""

from sqlalchemy.orm import Session

from core.db import make_engine
from pipeline.expire import expire_missing_opportunities


def main() -> None:
    engine = make_engine()
    with Session(engine) as session:
        closed_count = expire_missing_opportunities(session)
        session.commit()
        print(f"opportunities marked closed: {closed_count}", flush=True)


if __name__ == "__main__":
    main()
