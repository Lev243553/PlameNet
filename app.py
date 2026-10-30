import telebot
from telebot import types
from flask import Flask, request, jsonify
import requests
import sqlite3
import os

# --- НАСТРОЙКИ ---
TOKEN = "8959456335:AAFmQZmvsWuma4U0TZhIpBQJ8Kd2VOHwRN8" 
POLZA_API_KEY = "pza_qGQO8ZXtNks1OxNxKOGjd-Y01K9i-E0g"
API_URL = "https://polza.ai/api/v1/media"
ADMIN_ID = 7031603236
DB_PATH = "app.db"

bot = telebot.TeleBot(TOKEN, threaded=True)
app = Flask(__name__)

# --- БАЗА ДАННЫХ ---
def get_conn(): return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()
init_db()

def get_balance(user_id):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, 0))
        conn.commit()
        res = 0
    else:
        res = row[0]
    conn.close()
    return res

def update_balance(user_id, amount):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, ?)", (user_id, 0))
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

# --- БОТ (Telebot) ---
@bot.message_handler(commands=['start'])
def start(message):
    markup = types.InlineKeyboardMarkup()
    # Кнопка для открытия PWA. Замени URL на свой!
    web_app = types.WebAppInfo(url="https://твой-сайт.github.io/neuro-studio/")
    markup.add(types.InlineKeyboardButton("🚀 Открыть Студию", web_app=web_app))
    
    bot.send_message(message.chat.id, "Нажми на кнопку, чтобы открыть приложение:", reply_markup=markup)

@bot.message_handler(content_types=['web_app_data'])
def web_app_data_handler(message):
    # Ловим данные от Mini App
    try:
        import json
        data = json.loads(message.web_app_data.data)
        if data.get("action") == "buy_stars":
            amount = data.get("amount", 50) # 50 Stars по умолчанию
            
            # Выставляем счет за Stars
            markup = types.InlineKeyboardMarkup()
            pay_btn = types.InlineKeyboardButton(f"⭐ Оплатить {amount} Stars", pay=True)
            markup.add(pay_btn)
            
            bot.send_invoice(
                chat_id=message.chat.id,
                title="Пополнение баланса",
                description=f"+{amount} генераций",
                invoice_payload=f"buy_{amount}",
                provider_token="", 
                currency="XTR",
                prices=[types.LabeledPrice(label="Stars", amount=amount)],
                reply_markup=markup
            )
    except Exception as e:
        print(f"Ошибка web_app_data: {e}")

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    payload = message.successful_payment.invoice_payload
    if payload.startswith("buy_"):
        amount = int(payload.split("_")[1])
        update_balance(message.from_user.id, amount)
        bot.send_message(message.chat.id, f"✅ Баланс пополнен на {amount}⭐!\nОткрой приложение снова (/start).")

# --- САЙТ (Flask API) ---
@app.route('/api/balance', methods=['POST'])
def api_balance():
    data = request.json
    user_id = data.get('user_id')
    if not user_id: return jsonify({"error": "No user"}), 400
    return jsonify({"balance": get_balance(user_id)})

@app.route('/api/generate', methods=['POST'])
def api_generate():
    data = request.json
    user_id = data.get('user_id')
    prompt = data.get('prompt')
    model_type = data.get('model') # image или audio
    
    # Проверяем баланс
    bal = get_balance(user_id)
    cost = 10 if model_type == 'image' else 15
    
    if bal < cost:
        return jsonify({"error": "Недостаточно звезд"}), 403

    # Выбираем модель Polza
    polza_model = "openai/gpt-image-1.5" if model_type == 'image' else "suno/sounds"

    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}
    if model_type == 'image':
        payload = {"model": polza_model, "input": {"prompt": prompt, "aspect_ratio": "1:1"}, "async": False}
    else:
        payload = {"model": polza_model, "input": {"prompt": prompt}, "async": False}

    try:
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
        res_data = resp.json()

        if resp.status_code != 200:
            return jsonify({"error": res_data.get('error', {}).get('message', 'Ошибка API')})

        # Ожидание
        if res_data.get("status") == "pending":
            import time
            for _ in range(30):
                time.sleep(3)
                chk = requests.get(f"{API_URL}/{res_data['id']}", headers=headers).json()
                if chk.get("status") == "completed":
                    res_data = chk; break
                if chk.get("status") == "failed":
                    return jsonify({"error": "Генерация не удалась"})

        url = None
        if "data" in res_data and isinstance(res_data["data"], list):
            url = res_data["data"][0].get("url")
        elif "url" in res_data:
            url = res_data["url"]

        if not url: return jsonify({"error": "Ошибка: API не вернул ссылку"})

        # Списываем баланс только если генерация прошла успешно
        update_balance(user_id, -cost)
        
        return jsonify({"type": model_type, "url": url})

    except Exception as e:
        return jsonify({"error": str(e)})

# --- ЗАПУСК ---
if __name__ == "__main__":
    import threading
    def run_bot(): bot.infinity_polling()
    threading.Thread(target=run_bot, daemon=True).start()
    
    print("🚀 Сервер запущен.")
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
