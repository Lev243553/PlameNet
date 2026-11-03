import telebot
from telebot import types
import requests
import time
import os
import sqlite3
import datetime
import random
import string
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# --- НАСТРОЙКИ ИЗ .ENV ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
MYSTARS_API_KEY = os.getenv("MYSTARS_API_KEY")
TON_WALLET = os.getenv("TON_WALLET")

# База данных
DB_PATH = "shop_bot.db"

# --- КУРСЫ ---
TON_USD_RATE = 1.35     # Курс TON к доллару (примерный)

# --- ПАКЕТЫ ЗВЁЗД (в USD) ---
STAR_PACKAGES = {
    50: {"usd": 1.30},
    100: {"usd": 2.40},
    250: {"usd": 5.80},
    500: {"usd": 11.50},
    1000: {"usd": 22.00}
}

# --- ПАКЕТЫ PREMIUM (ЦЕНЫ В TON) ---
PREMIUM_PACKAGES = {
    3: {"ton": 14.0},    
    6: {"ton": 23.0},    
    12: {"ton": 40.0}    
}

bot = telebot.TeleBot(TOKEN, threaded=True)
user_data = {}

# ==========================================
# 1. БАЗА ДАННЫХ
# ==========================================
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, 
        username TEXT, 
        is_banned INTEGER DEFAULT 0,
        total_bought INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        code TEXT PRIMARY KEY,
        user_id INTEGER,
        username TEXT,
        product_type TEXT,
        amount INTEGER,
        price_usd REAL,
        status TEXT DEFAULT 'pending'
    )''')
    conn.commit()
    conn.close()

init_db()

def db_get_user(user_id):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT username, is_banned, total_bought FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone(); conn.close()
    if row:
        return {"username": row[0], "is_banned": bool(row[1]), "total_bought": row[2]}
    return None

def db_add_user(user_id, username):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit(); conn.close()

# ==========================================
# 2. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def get_main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(types.KeyboardButton("⭐ Купить звёзды"), types.KeyboardButton("💎 Купить Premium"))
    markup.add(types.KeyboardButton("👤 Мой профиль"), types.KeyboardButton("📞 Поддержка"))
    if user_id == ADMIN_ID:
        markup.add(types.KeyboardButton("🛡 Админ-панель"))
    return markup

def gen_code():
    return "PAY-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

# ==========================================
# 3. ОБРАБОТЧИКИ
# ==========================================
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    uname = message.from_user.username or f"id{uid}"
    
    if not db_get_user(uid):
        db_add_user(uid, uname)

    bot.send_message(
        uid,
        f"👋 Привет, @{uname}!\n\n"
        f"Добро пожаловать в магазин звёзд и Premium.\n"
        f"💳 Оплата принимается в криптовалюте (TON).",
        reply_markup=get_main_menu(uid),
        parse_mode="HTML"
    )

@bot.message_handler(func=lambda message: message.text == "👤 Мой профиль")
def profile(message):
    uid = message.from_user.id
    u = db_get_user(uid)
    if not u: return start(message)
    
    text = (
        f"👤 <b>Твой профиль:</b>\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"📛 Юзернейм: @{u['username']}\n"
        f"🛒 Всего куплено: {u['total_bought']} раз"
    )
    bot.send_message(message.chat.id, text, parse_mode="HTML")

@bot.message_handler(func=lambda message: message.text == "📞 Поддержка")
def support(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Написать в поддержку", url="https://t.me/crptworking"))
    bot.send_message(message.chat.id, "Возникли вопросы? Напиши нам:", reply_markup=markup)

# --- ЗВЁЗДЫ (Только TON) ---
@bot.message_handler(func=lambda message: message.text == "⭐ Купить звёзды")
def buy_stars_menu(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for stars, data in STAR_PACKAGES.items():
        price_ton = round(data['usd'] / TON_USD_RATE, 3)
        btn = types.InlineKeyboardButton(
            f"⭐ {stars} Stars — {price_ton} TON", 
            callback_data=f"buy_stars_{stars}"
        )
        markup.add(btn)
    bot.send_message(message.chat.id, "Выбери пакет звёзд:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_stars_"))
def process_stars_choice(call):
    bot.answer_callback_query(call.id)
    stars = int(call.data.split("_")[2])
    price_usd = STAR_PACKAGES[stars]['usd']
    price_ton = round(price_usd / TON_USD_RATE, 3)
    
    uid = call.from_user.id
    uname = call.from_user.username or f"id{uid}"
    
    code = gen_code()
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO orders (code, user_id, username, product_type, amount, price_usd) VALUES (?, ?, ?, ?, ?, ?)",
              (code, uid, uname, "stars", stars, price_usd))
    conn.commit(); conn.close()
    
    text = (
        f"✅ <b>Заказ сформирован</b>\n\n"
        f"Товар: {stars} Stars\n"
        f"К оплате: <b>{price_ton} TON</b>\n\n"
        f"💳 <b>Реквизиты для оплаты:</b>\n"
        f"Кошелек: <code>{TON_WALLET}</code>\n"
        f"⚠️ <b>В комментарии к переводу обязательно укажи:</b> <code>{code}</code>\n\n"
        f"После перевода нажми кнопку ниже и пришли хеш транзакции."
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Я оплатил", callback_data=f"confirm_pay_{code}"))
    
    bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")

# --- PREMIUM (Только TON) ---
@bot.message_handler(func=lambda message: message.text == "💎 Купить Premium")
def buy_premium_menu(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for months, data in PREMIUM_PACKAGES.items():
        price_ton = data['ton']
        btn = types.InlineKeyboardButton(
            f"💎 Premium {months} мес. — {price_ton} TON", 
            callback_data=f"buy_prem_{months}"
        )
        markup.add(btn)
    bot.send_message(message.chat.id, "Выбери срок Premium:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_prem_"))
def process_premium_choice(call):
    bot.answer_callback_query(call.id)
    months = int(call.data.split("_")[2])
    
    price_ton = PREMIUM_PACKAGES[months]['ton']
    
    uid = call.from_user.id
    uname = call.from_user.username or f"id{uid}"
    
    code = gen_code()
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO orders (code, user_id, username, product_type, amount, price_usd) VALUES (?, ?, ?, ?, ?, ?)",
              (code, uid, uname, "premium", months, price_ton))
    conn.commit(); conn.close()
    
    text = (
        f"✅ <b>Заказ сформирован</b>\n\n"
        f"Товар: Premium на {months} мес.\n"
        f"К оплате: <b>{price_ton} TON</b>\n\n"
        f"💳 <b>Реквизиты для оплаты:</b>\n"
        f"Кошелек: <code>{TON_WALLET}</code>\n"
        f"⚠️ <b>В комментарии к переводу обязательно укажи:</b> <code>{code}</code>\n\n"
        f"После перевода нажми кнопку ниже и пришли хеш транзакции."
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Я оплатил", callback_data=f"confirm_pay_{code}"))
    
    bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")

# --- ПОДТВЕРЖДЕНИЕ ОПЛАТЫ (КЛИЕНТ) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_pay_"))
def user_paid(call):
    bot.answer_callback_query(call.id, "✅ Заявка отправлена админу на проверку.")
    code = call.data.split("_")[2]
    
    bot.send_message(
        ADMIN_ID,
        f"🔔 <b>Пользователь нажал 'Я оплатил'!</b>\n"
        f"Код заказа: <code>{code}</code>\n"
        f"Проверь поступление TON и выдай товар через админку.",
        parse_mode="HTML"
    )

# ==========================================
# 4. АДМИН-ПАНЕЛЬ
# ==========================================
@bot.message_handler(func=lambda message: message.text == "🛡 Админ-панель")
def admin_panel(message):
    if message.from_user.id != ADMIN_ID: return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📦 Выдать заказ", callback_data="adm_give"),
        types.InlineKeyboardButton("📊 Статистика", callback_data="adm_stats")
    )
    markup.add(
        types.InlineKeyboardButton("🚫 Забанить", callback_data="adm_ban"),
        types.InlineKeyboardButton("✅ Разбанить", callback_data="adm_unban")
    )
    markup.add(types.InlineKeyboardButton("📢 Рассылка", callback_data="adm_broadcast"))
    bot.send_message(message.chat.id, "🛡 <b>Админ-панель</b>", reply_markup=markup, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith("adm_"))
def admin_actions(call):
    if call.from_user.id != ADMIN_ID: return bot.answer_callback_query(call.id, "❌ Нет доступа.")
    bot.answer_callback_query(call.id)
    act = call.data.split("_")[1]

    if act == "give":
        msg = bot.send_message(call.message.chat.id, "Введи код заказа (например, <code>PAY-XXXXXX</code>):", parse_mode="HTML")
        bot.register_next_step_handler(msg, admin_fulfill_order)
    elif act == "stats":
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users"); total_users = c.fetchone()[0]
        c.execute("SELECT SUM(total_bought) FROM users"); total_bought = c.fetchone()[0] or 0
        conn.close()
        bot.send_message(call.message.chat.id, f"📊 Пользователей: {total_users}\n🛒 Покупок: {total_bought}")
    elif act == "ban":
        msg = bot.send_message(call.message.chat.id, "Напиши <code>@username</code> или ID для бана:")
        bot.register_next_step_handler(msg, admin_ban)
    elif act == "unban":
        msg = bot.send_message(call.message.chat.id, "Напиши <code>@username</code> или ID для разбана:")
        bot.register_next_step_handler(msg, admin_unban)
    elif act == "broadcast":
        msg = bot.send_message(call.message.chat.id, "Введи текст для рассылки:")
        bot.register_next_step_handler(msg, admin_broadcast)

def admin_fulfill_order(message):
    code = message.text.strip().upper()
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT user_id, username, product_type, amount, status FROM orders WHERE code = ?", (code,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        return bot.send_message(message.chat.id, "❌ Заказ с таким кодом не найден.")
    
    uid, uname, p_type, amount, status = row
    
    if status == "done":
        conn.close()
        return bot.send_message(message.chat.id, "❌ Этот заказ уже был выдан.")
        
    c.execute("UPDATE orders SET status = 'done' WHERE code = ?", (code,))
    c.execute("UPDATE users SET total_bought = total_bought + 1 WHERE user_id = ?", (uid,))
    conn.commit(); conn.close()
    
    bot.send_message(message.chat.id, f"✅ Заказ {code} выдан пользователю @{uname} ({amount} {p_type}).")
    
    try:
        bot.send_message(uid, f"🎉 <b>Твой заказ выполнен!</b>\nТы получил: {amount} {p_type}. Спасибо за покупку!", parse_mode="HTML")
    except: pass

def admin_ban(message):
    identifier = message.text.strip().replace("@", "")
    conn = get_conn(); c = conn.cursor()
    if identifier.isdigit(): c.execute("SELECT user_id, username FROM users WHERE user_id = ?", (int(identifier),))
    else: c.execute("SELECT user_id, username FROM users WHERE LOWER(username) = ?", (identifier.lower(),))
    row = c.fetchone()
    if row:
        uid, uname = row
        c.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (uid,))
        conn.commit(); bot.send_message(message.chat.id, f"✅ @{uname} забанен.")
    else: bot.send_message(message.chat.id, "❌ Пользователь не найден.")
    conn.close()

def admin_unban(message):
    identifier = message.text.strip().replace("@", "")
    conn = get_conn(); c = conn.cursor()
    if identifier.isdigit(): c.execute("SELECT user_id, username FROM users WHERE user_id = ?", (int(identifier),))
    else: c.execute("SELECT user_id, username FROM users WHERE LOWER(username) = ?", (identifier.lower(),))
    row = c.fetchone()
    if row:
        uid, uname = row
        c.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (uid,))
        conn.commit(); bot.send_message(message.chat.id, f"✅ @{uname} разбанен.")
    else: bot.send_message(message.chat.id, "❌ Пользователь не найден.")
    conn.close()

def admin_broadcast(message):
    conn = get_conn(); c = conn.cursor(); c.execute("SELECT user_id FROM users WHERE is_banned = 0"); users = c.fetchall(); conn.close()
    ok, fail = 0, 0
    for u in users:
        try: bot.send_message(u[0], message.text); ok += 1
        except: fail += 1
    bot.send_message(message.chat.id, f"✅ Рассылка: {ok} успешно, {fail} ошибок.")

# ==========================================
# ЗАПУСК
# ==========================================
if __name__ == "__main__":
    print("🚀 Магазин запущен.")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
