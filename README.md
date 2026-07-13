# BSC USDT Wallet Monitoring Telegram Bot

An asynchronous Telegram bot that listens to real-time BEP-20 USDT transfer events on the BNB Smart Chain (BSC) network via WebSockets.

## Commands Supported
* `/add 0xAddr1, 0xAddr2, 0xAddr3` - Bulk add wallets to tracking list.
* `/remove 0xAddr1, 0xAddr2` - Bulk remove wallets from tracking list.
* `/list` - Outputs all currently tracked wallet addresses.

## Setup Instructions

1. Clone this repository.
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to a new file named `.env`.
4. Fill in your configuration credentials inside `.env`.
5. Run the bot: `python main.py`
