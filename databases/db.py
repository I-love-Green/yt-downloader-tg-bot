import sqlite3

def init_db():
    conn = sqlite3.connect("user_actions.db")
    cur = conn.cursor()