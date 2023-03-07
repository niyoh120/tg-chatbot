import typing as t
import html
import json
import structlog
import traceback
import functools as ft
import enum
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    filters,
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    PicklePersistence,
    InvalidCallbackData,
)
import pydantic as pyd


import bing
import chatgpt


BOT_TYPE_MAP = {
    "bing": bing.Bot,
    "chatgpt": chatgpt.Bot,
}

logger = structlog.get_logger(__name__)


class Config(pyd.BaseSettings):
    bot_token: str
    bot_data_path: str
    exception_send_chat_id: t.Optional[int] = None

    class Config:
        env_file = ".env"
        env_prefix = "telegram_"


config = Config()  # type: ignore

app = ApplicationBuilder()
app = app.arbitrary_callback_data(True)
persistence = PicklePersistence(filepath=config.bot_data_path)
app = app.persistence(persistence)
app = app.token(config.bot_token)
app = app.build()


def command_handler(command):
    """Decorator for command handlers."""

    def decorator(func):
        handler = CommandHandler(command, func)
        app.add_handler(handler)
        return func

    return decorator


def send_action(action):
    """Sends `action` while processing func command."""

    def decorator(func):
        @ft.wraps(func)
        async def command_func(update, context, *args, **kwargs):
            await context.bot.send_chat_action(
                chat_id=update.effective_message.chat_id, action=action
            )
            return await func(update, context, *args, **kwargs)

        return command_func

    return decorator


def log(fn):
    ft.wraps(fn)

    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info(f"update: {update.to_json()}")
        logger.info(f"bot_data: {context.bot_data}")
        logger.info(f"chat_data: {context.chat_data}")
        logger.info(f"user_data: {context.user_data}")
        return await fn(update, context)

    return wrapper


def get_or_create_chatbot(
    context: ContextTypes.DEFAULT_TYPE,
    engine="bing",
):
    chat_data = context.chat_data
    assert engine in BOT_TYPE_MAP
    assert chat_data is not None
    bot_data = chat_data.get("bot_data", None)
    if bot_data is None:
        bot_id = str(uuid4())
        return BOT_TYPE_MAP[engine](bot_id)
    return BOT_TYPE_MAP[bot_data["info"]["engine"]].deserialize(bot_data)


def save_bot(context: ContextTypes.DEFAULT_TYPE, bot):
    chat_data = context.chat_data
    assert chat_data is not None
    chat_data["bot_data"] = bot.serialize()


async def reply_markdown(update: Update, text: str, **kwargs):
    assert update.message is not None
    reply_markup = kwargs.pop("reply_markup", ReplyKeyboardRemove())
    await update.message.reply_markdown_v2(
        text=text, reply_markup=reply_markup, **kwargs
    )


async def reply_text(update: Update, text: str, **kwargs):
    assert update.message is not None
    reply_markup = kwargs.pop("reply_markup", ReplyKeyboardRemove())
    await update.message.reply_text(text=text, reply_markup=reply_markup, **kwargs)


@command_handler("reset")
@log
async def reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.message is not None
    bot = get_or_create_chatbot(context)
    await bot.reset()
    save_bot(context, bot)

    await reply_text(update, text="好了，我已经为新的对话重置了我的大脑。你现在想聊些什么?")


@command_handler("settings")
@log
async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert context.args is not None

    help_text = [
        r"\- /setStyle: 设置聊天风格",
        r"\- /setEngine 设置聊天引擎",
    ]
    text = "\n".join(help_text)
    await reply_markdown(update, text)


async def invalid_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Informs the user that the button is no longer available."""

    query = update.callback_query
    assert query is not None
    await query.answer()
    await query.edit_message_text("该键盘已经失效.")


class ChatStyleChoices(enum.Enum):
    creative = "creative"
    balanced = "balanced"
    precise = "precise"


@command_handler("setStyle")
@log
async def set_style_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = get_or_create_chatbot(context)
    if bot.engine not in ("bing"):
        await reply_text(update, "该聊天引擎不支持设置聊天风格.")
        return

    keyboard = [
        [InlineKeyboardButton(e.value, callback_data=e) for e in ChatStyleChoices]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await reply_text(update, "请选择聊天风格.", reply_markup=reply_markup)


async def style_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    assert query is not None

    style_to_config = t.cast(ChatStyleChoices, query.data)  #  type: ignore
    bot = get_or_create_chatbot(context)
    bot.style = style_to_config.value
    save_bot(context, bot)

    await query.answer()
    await query.edit_message_text(f"当前聊天风格为: [{style_to_config}]")
    context.drop_callback_data(query)
    return


class ChatEngineChoices(enum.Enum):
    bing = "bing"
    chatgpt = "chatgpt"


@command_handler("setEngine")
@log
async def set_engine_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(e.value, callback_data=e) for e in ChatEngineChoices]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await reply_text(update, "请选择聊天引擎.", reply_markup=reply_markup)


async def engine_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    assert query is not None

    chat_data = context.chat_data
    assert chat_data is not None

    engine = t.cast(ChatEngineChoices, query.data)  #  type: ignore
    assert engine.value in BOT_TYPE_MAP

    bot_id = str(uuid4())
    bot = BOT_TYPE_MAP[engine.value](bot_id)
    save_bot(context, bot)

    await query.answer()
    await query.edit_message_text(f"当前聊天引擎为: [{engine.value}]")
    context.drop_callback_data(query)
    return


@command_handler("info")
@log
async def info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = get_or_create_chatbot(context)
    text = "\n".join([rf"\- {k}: {v}" for k, v in bot.info().items()])

    await reply_markdown(update, text)
    return


@command_handler("chatId")
@log
async def chat_id_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.message is not None
    await reply_text(update, f"当前聊天ID为: {update.message.chat_id}")
    return


@command_handler("help")
@log
async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = [
        r"\- /help: 帮助",
        r"\- /settings: 列出机器人设置",
        r"\- /info: 获取机器人信息",
        r"\- /reset: 重置对话",
        r"\- /chatID: 获取聊天ID",
    ]
    text = "\n".join(help_text)
    await reply_markdown(update, text)
    return


@log
@send_action(ChatAction.TYPING)
async def ask_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.message is not None

    prompt = update.message.text
    if prompt is None or prompt.strip() == "":
        return
    bot = get_or_create_chatbot(context)
    try:
        text = await bot.ask(
            prompt,
        )
    except Exception:
        text = "出错了"
        await reply_text(update, text, quote=True)
        raise

    save_bot(context, bot)

    keyboard = [[q] for q in bot.suggested_questions]
    if len(keyboard) > 0:
        reply_markup = ReplyKeyboardMarkup(keyboard)
    else:
        reply_markup = ReplyKeyboardRemove()
    await reply_text(update, text, quote=True, reply_markup=reply_markup)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    # Log the error before we do anything else, so we can see it even if something breaks.

    assert context.error is not None
    try:
        raise context.error
    except:
        logger.exception("Exception while handling an update.")

    if config.exception_send_chat_id is not None:
        # traceback.format_exception returns the usual python message about an exception, but as a
        # list of strings rather than a single string, so we have to join them together.
        tb_list = traceback.format_exception(
            None, context.error, context.error.__traceback__
        )
        tb_string = "".join(tb_list)

        # Build the message with some markup and additional information about what happened.
        # You might need to add some logic to deal with messages longer than the 4096 character limit.
        update_str = update.to_dict() if isinstance(update, Update) else str(update)
        message = (
            "An exception was raised while handling an update\n"
            "<pre>update ="
            f" {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}"
            "</pre>\n\n"
            f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n"
            f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n"
            f"<pre>{html.escape(tb_string)}</pre>"
        )

        # Finally, send the message
        await context.bot.send_message(
            chat_id=config.exception_send_chat_id,
            text=message,
            parse_mode=ParseMode.HTML,
        )


def main():
    logger.info(f"bot config: {config.dict()}")
    logger.info(f"bing config: {bing.config.dict()}")
    logger.info(f"chatgpt config: {chatgpt.config.dict()}")

    ask_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), ask_callback)
    app.add_handler(ask_handler)
    app.add_handler(
        CallbackQueryHandler(style_button_callback, pattern=ChatStyleChoices)
    )
    app.add_handler(
        CallbackQueryHandler(engine_button_callback, pattern=ChatEngineChoices)
    )
    app.add_handler(
        CallbackQueryHandler(invalid_button_callback, pattern=InvalidCallbackData)
    )
    app.add_error_handler(error_handler)

    app.run_polling()


if __name__ == "__main__":
    main()
