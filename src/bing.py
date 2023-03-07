from __future__ import annotations

import typing as t
import json
import copy

import structlog
import httpx
from EdgeGPT import ChatHub
import pydantic as pyd

import bot

logger = structlog.get_logger(__name__)


class Config(pyd.BaseSettings):
    cookie_file: str = "./cookie.json"

    class Config:
        env_file = ".env"
        env_prefix = "bing_"


class Conversation:
    """
    Conversation API
    """

    def __init__(self, context) -> None:
        self.struct = context


class Client(ChatHub):
    def __init__(self, context: t.Dict[str, t.Any]) -> None:
        conv = Conversation(context)
        super().__init__(conv)  # type: ignore
        self.request.invocation_id = context["invocation_id"]


HEADERS_INIT_CONVER = {
    "authority": "edgeservices.bing.com",
    "accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "accept-language": "en-US,en;q=0.9",
    "cache-control": "max-age=0",
    "sec-ch-ua": '"Chromium";v="110", "Not A(Brand";v="24", "Microsoft Edge";v="110"',
    "sec-ch-ua-arch": '"x86"',
    "sec-ch-ua-bitness": '"64"',
    "sec-ch-ua-full-version": '"110.0.1587.69"',
    "sec-ch-ua-full-version-list": (
        '"Chromium";v="110.0.5481.192", "Not A(Brand";v="24.0.0.0", "Microsoft'
        ' Edge";v="110.0.1587.69"'
    ),
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-model": '""',
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua-platform-version": '"15.0.0"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like"
        " Gecko) Chrome/110.0.0.0 Safari/537.36 Edg/110.0.1587.69"
    ),
    "x-edge-shopping-flag": "1",
    "x-forwarded-for": "1.1.1.1",
}


async def create_conversation_context(cookies) -> t.Dict[str, t.Any]:
    async with httpx.AsyncClient() as session:
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    " (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
                ),
            },
        )
        for cookie in cookies:
            session.cookies.set(cookie["name"], cookie["value"])
        url = "https://edgeservices.bing.com/edgesvc/turing/conversation/create"
        # Send GET request
        response = await session.get(
            url,
            timeout=30,
            headers=HEADERS_INIT_CONVER,
        )
        if response.status_code != 200:
            logger.warn(f"Status code:{response.status_code}, message:{response.text}")
            raise RuntimeError("Authentication failed")
        try:
            context = response.json()
            if context["result"]["value"] == "UnauthorizedRequest":
                raise RuntimeError(context["result"]["message"])
        except (json.decoder.JSONDecodeError, RuntimeError) as exc:
            raise RuntimeError(
                "Authentication failed. You have not been accepted into the beta.",
            ) from exc
        context["invocation_id"] = 0
        return context


class Bot(bot.Bot):
    _cookies = None
    engine = "bing"

    def __init__(
        self, bot_id: str, style: str = "balanced", context=None, count=0, **kwargs
    ) -> None:
        super().__init__(bot_id=bot_id, count=count, **kwargs)
        self.style = style
        self._context = context
        if self._context is not None:
            self._client = Client(self._context)
        else:
            self._client = None
        self._count = count

    async def ask(self, prompt: str) -> str:

        async def ask(
            prompt: str,
            conversation_style: t.Optional[str] = None,
        ) -> t.Optional[t.Dict[str, t.Any]]:
            """
            Ask a question to the bot
            """
            if self._context is None:
                self._context = await create_conversation_context(self._cookies)
                self._client = Client(self._context)
            assert self._client is not None
            response = None
            async for final, response in self._client.ask_stream(
                prompt=prompt,
                conversation_style=conversation_style,  # type: ignore
            ):
                if final:
                    break

            await self._client.close()
            return response  # type: ignore

        self._count += 1
        response = await ask(prompt, conversation_style=self.style)  # type: ignore
        if response is None:
            return "No response"
        logger.info(f"[bot:{self.bot_id}] receive response: [{response}]")
        answer = response["item"]["messages"][1]
        self.suggested_questions = [res["text"] for res in answer["suggestedResponses"]]
        # return answer["text"]
        return answer["adaptiveCards"][0]["body"][0]["text"]

    async def reset(self):
        if self._client is not None:
            await self._client.close()
        self._context = await create_conversation_context(self._cookies)
        self._client = Client(self._context)

    async def close(self):
        if self.closed:
            return
        
        self._context = None
        if self._client is not None:
            await self._client.close()
            self._client = None
        
        self.closed = True

    def info(self):
        return dict(
            bot_id=self.bot_id, engine=self.engine, style=self.style, count=self._count
        )

    def serialize(self) -> t.Dict[str, t.Any]:
        if self._context is not None:
            assert self._client is not None
            context = copy.deepcopy(dict(**self._context))
            context["invocation_id"] = self._client.request.invocation_id
        else:
            context = None
        info = self.info()
        return dict(info=info, context=context)

    @classmethod
    def deserialize(cls, data: t.Dict[str, t.Any]) -> Bot:
        info = data["info"]
        context = data["context"]
        return cls(
            bot_id=info["bot_id"],
            style=info["style"],
            count=info["count"],
            context=context,
        )


config = Config()
with open(config.cookie_file, "r") as f:
    Bot._cookies = json.load(f)
