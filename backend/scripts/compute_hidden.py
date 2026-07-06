"""Recompute deterministic hidden-opportunity flags."""

from sqlalchemy.orm import Session

from core.db import make_engine
from pipeline.hidden import recompute_hidden


def main() -> None:
    engine = make_engine()
    with Session(engine) as session:
        hidden_count = recompute_hidden(session)
        session.commit()
        print(f"hidden opportunities: {hidden_count}", flush=True)


if __name__ == "__main__":
    main()
