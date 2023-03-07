from __future__ import annotations

import typing as t

from revChatGPT.V1 import AsyncChatbot
import pydantic as pyd

import bot


class Config(pyd.BaseSettings):
    access_token: str

    class Config:
        env_file = ".env"
        env_prefix = "chatgpt_"


config = Config()  # type: ignore


class Bot(bot.Bot):
    engine = "chatgpt"

    def __init__(self, bot_id: str, count=0, context=None, **kwargs) -> None:
        super().__init__(bot_id=bot_id, count=count, **kwargs)
        self._bot = None
        self._context = (
            context
            if context is not None
            else dict(conversation_id=None, parent_id=None)
        )

    async def _init_bot(self):
        if self._bot is None:
            self._bot = AsyncChatbot(
                config=config.dict(),
                conversation_id=self._context["conversation_id"],
                parent_id=self._context["parent_id"],
            )
            if self._context["conversation_id"] is None:
                await self._bot.clear_conversations()

                response = await self._ask_bot("chatgpt")
                if response is None:
                    raise RuntimeError("chatgpt init failed")
            title = f"[chatbot][id:{self.bot_id}]"
            await self._bot.change_title(self._context["conversation_id"], title)  # type: ignore

    async def _ask_bot(self, prompt: str) -> t.Optional[dict[str, t.Any]]:
        response = None
        async for r in self._bot.ask(prompt):  # type: ignore
            response = r
        if response is not None:
            self._context["conversation_id"] = response["conversation_id"]
            self._context["parent_id"] = response["parent_id"]
        return response

    async def ask(self, prompt: str) -> str:
        await self._init_bot()
        response = await self._ask_bot(prompt)
        await self._bot.session.aclose()  # type: ignore
        self._bot = None
        if response is None:
            return "No response"
        return response["message"]

    async def reset(self):
        conv_id = self._context["conversation_id"]
        self._context = dict(conversation_id=None, parent_id=None)
        if self._bot is not None:
            if conv_id is not None:
                await self._bot.delete_conversation(conv_id)
            await self._bot.session.aclose()  # type: ignore
            self._bot = None

    def serialize(self):
        return dict(info=self.info(), context=self._context)

    @classmethod
    def deserialize(cls, data: t.Dict[str, t.Any]) -> Bot:
        info = data["info"]
        return cls(bot_id=info["bot_id"], count=info["count"], context=data["context"])
