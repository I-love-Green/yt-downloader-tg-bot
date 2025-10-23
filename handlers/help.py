from aiogram import Router, types
from aiogram.filters import Command

router = Router()

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer("Commands available:\n/start - Start the bot\n"
    "/help - Show this help message\n/download <url> - Download an Envato item by its link\n"
    "/files - Show list your files\n/buy - Buy diamonds for downloads\n/support - Contact support")