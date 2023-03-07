from __future__ import annotations

import typing as t


class Bot:
    engine = "unknown"

    def __init__(
        self,
        bot_id: str,
        count=0,
        **kwargs,
    ):
        self.bot_id = bot_id
        self.count = count
        self.suggested_questions = []

    async def ask(self, prompt: str) -> str:
        raise NotImplementedError

    async def reset(self):
        raise NotImplementedError

    def info(self):
        return dict(bot_id=self.bot_id, engine=self.engine, count=self.count)

    def serialize(self) -> t.Dict[str, t.Any]:
        raise NotImplementedError

    @classmethod
    def deserialize(cls, data: t.Dict[str, t.Any]) -> Bot:
        raise NotImplementedError
