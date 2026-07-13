import os
import logging
import asyncio
import re
import threading
import json
import websockets
from flask import Flask
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from web3 import Web3

import database

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TARGET_CHAT_ID = os.getenv("TARGET_CHAT_ID")
BSC_WS_URL = os.getenv("BSC_WS_URL", "wss://bsc-rpc.publicnode.com")
BSC_HTTP_URL = os.getenv("BSC_HTTP_URL", "https://bsc-rpc.publicnode.com")

# USDT BEP-20 Configuration
USDT_CONTRACT = "0x55d398326f99059ff775485246999027b3197955"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
TOKEN_DECIMALS = 10**18
USDT_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]

# Logging setup
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

# Global runtime cache synchronized with DB
runtime_wallets = set()
web3_http = Web3(Web3.HTTPProvider(BSC_HTTP_URL))
usdt_contract = web3_http.eth.contract(
    address=Web3.to_checksum_address(USDT_CONTRACT),
    abi=USDT_ABI
)

# --- DUMMY WEB SERVER FOR RENDER ---
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is awake and monitoring the blockchain!"

def run_web_server():
    # Render assigns a port dynamically via the PORT environment variable
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)
# -----------------------------------

def clean_and_parse_addresses(text: str) -> list:
    """Extracts valid EVM hex addresses from comma or space-separated user strings."""
    raw_tokens = re.split(r'[,\s]+', text)
    valid_addresses = []
    for token in raw_tokens:
        clean_token = token.strip().lower()
        if re.match(r"^0x[a-f0-9]{40}$", clean_token):
            valid_addresses.append(clean_token)
    return valid_addresses

def get_wallet_usdt_balance(address: str):
    """Fetch current USDT balance for a wallet using HTTP RPC."""
    try:
        checksum_address = Web3.to_checksum_address(address)
        balance_raw = usdt_contract.functions.balanceOf(checksum_address).call()
        return balance_raw / TOKEN_DECIMALS
    except Exception as exc:
        logging.warning(f"Could not fetch USDT balance for {address}: {exc}")
        return None

def format_usdt_balance(balance) -> str:
    if balance is None:
        return "N/A"
    return f"{balance:,.2f} USDT"

async def add_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: `/add 0xAddress1, 0xAddress2`", parse_mode="Markdown")
        return

    raw_input = " ".join(context.args)
    addresses = clean_and_parse_addresses(raw_input)
    
    if not addresses:
        await update.message.reply_text("❌ No valid BSC addresses detected.")
        return

    newly_added = database.add_wallets_db(addresses)
    
    # Refresh local runtime cache
    global runtime_wallets
    runtime_wallets = database.get_all_wallets()
    
    await update.message.reply_text(f"✅ Added {newly_added} new wallet(s). Total tracking: {len(runtime_wallets)}")

async def remove_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: `/remove 0xAddress1, 0xAddress2`", parse_mode="Markdown")
        return

    raw_input = " ".join(context.args)
    addresses = clean_and_parse_addresses(raw_input)
    
    if not addresses:
        await update.message.reply_text("❌ No valid BSC addresses detected.")
        return

    removed = database.remove_wallets_db(addresses)
    
    # Refresh local runtime cache
    global runtime_wallets
    runtime_wallets = database.get_all_wallets()
    
    await update.message.reply_text(f"🗑️ Removed {removed} wallet(s). Total tracking: {len(runtime_wallets)}")

async def list_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not runtime_wallets:
        await update.message.reply_text("No wallets are currently being monitored.")
        return
    
    wallet_list = "\n".join([f"- `{w}`" for w in runtime_wallets])
    await update.message.reply_text(f"📋 **Monitored Wallets ({len(runtime_wallets)}):**\n{wallet_list}", parse_mode="Markdown")

async def blockchain_monitor(application: Application):
    """Background loop subscribing to WebSocket logs using pure raw JSON-RPC."""
    payload = {
        "id": 1,
        "jsonrpc": "2.0",
        "method": "eth_subscribe",
        "params": ["logs", {
            "address": USDT_CONTRACT, 
            "topics": [TRANSFER_TOPIC]
        }]
    }
    
    while True:
        try:
            logging.info("Connecting to BSC WebSocket natively...")
            
            # Connect directly bypassing web3.py
            async with websockets.connect(BSC_WS_URL, ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps(payload))
                sub_response = await ws.recv()
                logging.info(f"Connected to BSC Log Stream. Response: {sub_response}")
                
                # Listen to incoming blocks infinitely
                async for message in ws:
                    data = json.loads(message)
                    
                    if "params" in data and "result" in data["params"]:
                        log = data["params"]["result"]
                        topics = log.get('topics', [])
                        
                        # USDT Transfers always have 3 topics (Signature, From, To)
                        if len(topics) >= 3:
                            from_address = "0x" + topics[1][-40:].lower()
                            to_address = "0x" + topics[2][-40:].lower()
                            
                            # Check if the sender or receiver matches our DB
                            if from_address in runtime_wallets or to_address in runtime_wallets:
                                value_hex = log.get('data', '0x0')
                                value_wei = int(value_hex, 16) if value_hex != '0x' else 0
                                value_usdt = value_wei / TOKEN_DECIMALS  # BSC USDT uses 18 decimals
                                
                                tx_hash = log.get('transactionHash', '')
                                from_balance, to_balance = await asyncio.gather(
                                    asyncio.to_thread(get_wallet_usdt_balance, from_address),
                                    asyncio.to_thread(get_wallet_usdt_balance, to_address),
                                )
                                
                                msg = (
                                    f"🚨 **USDT Activity Detected!**\n\n"
                                    f"💰 **Amount:** {value_usdt:,.2f} USDT\n"
                                    f"📤 **From:** `{from_address}`\n"
                                    f"   **Balance:** {format_usdt_balance(from_balance)}\n"
                                    f"📥 **To:** `{to_address}`\n"
                                    f"   **Balance:** {format_usdt_balance(to_balance)}\n"
                                    f"🔗 [View on BscScan](https://bscscan.com/tx/{tx_hash})"
                                )
                                
                                await application.bot.send_message(
                                    chat_id=TARGET_CHAT_ID, 
                                    text=msg, 
                                    parse_mode="Markdown", 
                                    disable_web_page_preview=True
                                )
                                
        except Exception as e:
            logging.error(f"WebSocket disconnected or errored: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)

async def post_init(application: Application):
    """Starts the blockchain monitor inside the bot's native async event loop context."""
    asyncio.create_task(blockchain_monitor(application))

def main():
    # Start the dummy web server in a background thread
    threading.Thread(target=run_web_server, daemon=True).start()

    # Setup database and local runtime cache
    database.init_db()
    global runtime_wallets
    runtime_wallets = database.get_all_wallets()
    logging.info(f"Database loaded. Tracking {len(runtime_wallets)} wallets.")

    # Explicitly spawn the event loop for Python 3.14
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Initialize Telegram app with the post_init hook attached
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Commands
    application.add_handler(CommandHandler("add", add_wallet))
    application.add_handler(CommandHandler("remove", remove_wallet))
    application.add_handler(CommandHandler("list", list_wallets))

    # Run the bot polling mechanism
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
