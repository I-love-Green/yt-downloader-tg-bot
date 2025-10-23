from aiogram import types

kb = types.InlineKeyboardMarkup(
    inline_keyboard=[
        [types.InlineKeyboardButton(text="Download your file", callback_data="download_file")],
        [types.InlineKeyboardButton(text="Help", callback_data="help")],
        [types.InlineKeyboardButton(text="Support", callback_data="support")],
    ]
)