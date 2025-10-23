from aiogram import Router, types
from aiogram.filters import Command

router = Router()

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Welcome! I'm your bot for downloading Envato items. Use /help to see available commands.")
