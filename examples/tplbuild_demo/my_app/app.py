import logging
import os
from typing import List, Optional

import sqlalchemy as sa
from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy.ext.declarative import declarative_base

LOGGER = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DB_URL")

ModelBase = declarative_base()


class Message(ModelBase):
    __tablename__ = "messages"

    message_id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    message = sa.Column(sa.Text, nullable=False)
    author = sa.Column(sa.String(127), nullable=True)


class MessageOut(BaseModel):
    message_id: int
    message: str
    author: Optional[str] = None


class MessageIn(BaseModel):
    message: str
    author: Optional[str] = None


def make_app():
    app = FastAPI()

    engine = sa.create_engine(DATABASE_URL)
    ModelBase.metadata.create_all(engine)

    @app.get("/")
    async def status():
        return {"status": "ok"}

    @app.get("/message")
    def get_messages() -> List[MessageOut]:
        with engine.begin() as conn:
            return [
                MessageOut(**message_row)
                for message_row in conn.execute(sa.select(Message))
            ]

    @app.post("/message")
    def create_note(message: MessageIn) -> MessageOut:
        with engine.begin() as conn:
            response = conn.execute(sa.insert(Message).values(**message.dict()))
        return MessageOut(
            message_id=response.inserted_primary_key["message_id"],
            **message.dict(),
        )

    return app
