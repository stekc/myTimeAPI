from sqlalchemy import create_engine, String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

engine = create_engine("sqlite:///shift_database.sqlite3", echo=True)
# Create engine for sqlite


class Base(DeclarativeBase):
    pass


class SeenShift(Base):
    __tablename__ = "seen_shifts"
    id: Mapped[int] = mapped_column(primary_key=True)


with Session(engine) as session:
    Base.metadata.create_all(engine)
    session.commit()
