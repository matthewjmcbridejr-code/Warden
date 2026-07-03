# Marius Slack Integration (Future)

Slack integration is planned as a future, thin bridge using **Socket Mode**, keeping the local Marius API as the absolute source of truth. 

## Guidelines
- **Socket Mode Only**: Avoid exposing public webhooks to receive Slack events. Use Slack Socket Mode to maintain local safety.
- **Thin Bridge**: The Slack bot should purely translate Slack events into `127.0.0.1:6969` API calls, just like the Telegram bridge.
- **No Secrets**: Do not transmit raw `.env` files, credentials, or dangerous repo diffs through Slack messages.
- **Authorized Channels**: Only respond in allowed channels or direct messages matching authorized Slack user IDs.
