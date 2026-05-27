import asyncio
import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import httpx
import pandas as pd
import yfinance as yf

# ==========================================
# ⚙️ 核心設定區
# ==========================================
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


# ==========================================
# 📊 數據下載與關鍵價計算邏輯
# ==========================================
def calculate_stock_prices(stock_id):
    days_back = 365
    today = datetime.date.today()
    end_date = today + datetime.timedelta(days=1)
    start_date = today - datetime.timedelta(days=days_back)

    if len(stock_id) >= 4 and stock_id.isdigit():
        ticker_id = f"{stock_id}.TW"
        df_daily = yf.download(ticker_id, start=start_date, end=end_date, progress=False)
        if df_daily.empty:
            ticker_id = f"{stock_id}.TWO"
            df_daily = yf.download(ticker_id, start=start_date, end=end_date, progress=False)
    else:
        ticker_id = stock_id.upper()
        df_daily = yf.download(ticker_id, start=start_date, end=end_date, progress=False)

    if df_daily.empty or len(df_daily) < 2:
        return None

    if isinstance(df_daily.columns, pd.MultiIndex):
        df_daily.columns = df_daily.columns.get_level_values(0)

    t_day = df_daily.iloc[-1]
    p_day = df_daily.iloc[-2]
    
    t_h, t_l, t_c = float(t_day["High"]), float(t_day["Low"]), float(t_day["Close"])
    p_h, p_l = float(p_day["High"]), float(p_day["Low"])

    t_res = t_h + (t_h - t_l) * 0.382
    t_key = (t_h + t_l) / 2
    t_sup = t_l - (t_h - t_l) * 0.382

    p_res = p_h + (p_h - p_l) * 0.382
    p_key = (p_h + p_l) / 2
    p_sup = p_l - (p_h - p_l) * 0.382

    df_weekly = df_daily.resample("W-FRI").agg({"High": "max", "Low": "min"})
    w_key = float((df_weekly.iloc[-1]["High"] + df_weekly.iloc[-1]["Low"]) / 2)

    df_monthly = df_daily.resample("ME").agg({"High": "max", "Low": "min"})
    m_key = float((df_monthly.iloc[-1]["High"] + df_monthly.iloc[-1]["Low"]) / 2)

    return {
        "ticker_id": ticker_id, "current": t_c,
        "t_res": t_res, "t_key": t_key, "t_sup": t_sup,
        "p_res": p_res, "p_key": p_key, "p_sup": p_sup,
        "w_key": w_key, "m_key": m_key
    }


# ==========================================
# 🤖 原生 Telegram API 互動對接邏輯
# ==========================================
async def send_message(client, chat_id, text, reply_to_message_id=None):
    url = f"{API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    try:
        await client.post(url, json=payload)
    except Exception as e:
        print(f"發送失敗: {e}")

async def edit_message_text(client, chat_id, message_id, text):
    url = f"{API_URL}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    try:
        await client.post(url, json=payload)
    except Exception as e:
        print(f"編輯失敗: {e}")

async def handle_update(client, update):
    if "message" not in update or "text" not in update["message"]:
        return
    message = update["message"]
    chat_id = message["chat"]["id"]
    user_text = message["text"].strip()
    msg_id = message["message_id"]

    if user_text.lower() == "/start":
        await send_message(client, chat_id, "👋 **歡迎使用關鍵價看盤助手！**\n\n直接輸入股票代號查詢指標。")
        return

    # 查股價
    url = f"{API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": "🔍 正在大數據撈取與計算中，請稍候...", "reply_to_message_id": msg_id}
    try:
        resp = await client.post(url, json=payload)
        status_msg_id = resp.json()["result"]["message_id"]
    except:
        return

    try:
        p = calculate_stock_prices(user_text)
        if p is None:
            await edit_message_text(client, chat_id, status_msg_id, f"❌ 找不到股票代號 '{user_text}'。")
            return

        report_text = (
            f"📊 **股票標的：{p['ticker_id']}**\n"
            f"🟧 **股票現價：{p['current']:.2f}**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📅 **【今日技術指標】**\n"
            f"🟥 今日壓力：`{p['t_res']:.2f}`\n"
            f"🟨 今日關鍵：`{p['t_key']:.2f}`\n"
            f"🟩 今日支撐：`{p['t_sup']:.2f}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⏳ **【前日技術指標】**\n"
            f"🛑 前日壓力：`{p['p_res']:.2f}`\n"
            f"🪙 前日關鍵：`{p['p_key']:.2f}`\n"
            f"❇️ 前日支撐：`{p['p_sup']:.2f}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📈 **【長線波段參考】**\n"
            f"🔷 周關鍵價：`{p['w_key']:.2f}`\n"
            f"🔶 月關鍵價：`{p['m_key']:.2f}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💡 *提示：點擊數字可直接複製。*"
        )
        await edit_message_text(client, chat_id, status_msg_id, report_text)
    except Exception as e:
        await edit_message_text(client, chat_id, status_msg_id, "❌ 系統計算錯誤。")


# ==========================================
# 🌐 騙過 Render 免費方案的網頁外殼 (Web Server)
# ==========================================
class DummyWebService(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is running successfully!")

def run_web_server():
    # Render 規定免費網頁服務必須綁定在 0.0.0.0 且埠號為 10000
    server = HTTPServer(('0.0.0.0', 10000), DummyWebService)
    print("🌐 虛擬網頁端服務已啟動...")
    server.serve_forever()


# ==========================================
# 🚀 機器人主監聽迴圈
# ==========================================
async def main_bot_loop():
    print("🤖 機器人核心正在啟動...")
    offset = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                url = f"{API_URL}/getUpdates?offset={offset}&timeout=20"
                response = await client.get(url)
                if response.status_code == 200:
                    updates = response.json().get("result", [])
                    for update in updates:
                        asyncio.create_task(handle_update(client, update))
                        offset = update["update_id"] + 1
            except httpx.RequestError:
                await asyncio.sleep(3)
            except Exception as e:
                await asyncio.sleep(1)

if __name__ == "__main__":
    # 1. 開一條平行線程去跑虛擬網頁，用來應付 Render 免費機制
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    # 2. 主執行緒繼續跑非同步機器人
    try:
        asyncio.run(main_bot_loop())
    except KeyboardInterrupt:
        print("🛑 關閉程式")