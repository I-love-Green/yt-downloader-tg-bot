import sqlite3
import asyncio
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from environs import Env
from handlers.download import router as download_router
from handlers.start import router as start_router
from handlers.help import router as help_router

dp = Dispatcher()
dp.include_router(start_router)
dp.include_router(download_router)
dp.include_router(help_router)

async def main():
    env = Env()
    env.read_env(".env")
    bot = Bot(token=env('TOKEN'))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())