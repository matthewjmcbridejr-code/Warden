import pytest
import os
from unittest.mock import patch, MagicMock, AsyncMock

def test_telegram_doctor_missing_token(capsys):
    from src.marius.integrations.telegram_bot import doctor
    with patch.dict(os.environ, {}, clear=True):
        doctor()
        out = capsys.readouterr().out
        assert "TELEGRAM_BOT_TOKEN environment variable is missing" in out

@pytest.mark.anyio
async def test_telegram_brain_cmd():
    from src.marius.integrations.telegram_bot import brain_cmd
    update = MagicMock()
    update.effective_chat.id = 123
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["hello"]
    
    with patch("src.marius.integrations.telegram_bot.ALLOWED_IDS", [123]):
        with patch("src.marius.integrations.telegram_bot.api_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"response": "Hi there", "elapsed": 1.0}
            await brain_cmd(update, context)
            
            mock_req.assert_called_with("POST", "chat", data={"message": "hello", "brain_context": True})
            update.message.reply_text.assert_called_with("Hi there\n[1.0s]")

@pytest.mark.anyio
async def test_telegram_unauthorized():
    from src.marius.integrations.telegram_bot import handle_message
    update = MagicMock()
    update.effective_chat.id = 999
    update.message.text = "hello"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    
    with patch("src.marius.integrations.telegram_bot.ALLOWED_IDS", [123]):
        with patch("src.marius.integrations.telegram_bot.api_request", new_callable=AsyncMock) as mock_req:
            await handle_message(update, context)
            assert not mock_req.called
            update.message.reply_text.assert_called_with("Unauthorized.")

@pytest.mark.anyio
async def test_telegram_save_cmd():
    from src.marius.integrations.telegram_bot import save_cmd
    update = MagicMock()
    update.effective_chat.id = 123
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["new", "idea"]
    
    with patch("src.marius.integrations.telegram_bot.ALLOWED_IDS", [123]):
        with patch("src.marius.integrations.telegram_bot.api_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"ok": True}
            await save_cmd(update, context)
            
            mock_req.assert_called_with("POST", "brain/ingest/text", data={"text": "new idea", "title": "Telegram Note", "project": "personal", "tags": ["telegram"]})
            update.message.reply_text.assert_called_with("Saved to brain.")
