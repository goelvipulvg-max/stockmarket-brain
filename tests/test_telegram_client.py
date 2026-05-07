from unittest.mock import patch, MagicMock


def test_send_message_skips_if_no_token(capsys):
    from utils.telegram_client import send_message
    send_message("", "chat123", "hello")
    assert "missing" in capsys.readouterr().out


def test_send_message_skips_if_no_chat_id(capsys):
    from utils.telegram_client import send_message
    send_message("bot-token", "", "hello")
    assert "missing" in capsys.readouterr().out


def test_send_message_posts_correct_payload():
    mock_resp = MagicMock()
    mock_resp.ok = True
    with patch("utils.telegram_client.requests.post", return_value=mock_resp) as mock_post:
        from utils.telegram_client import send_message
        send_message("mytoken", "mychat", "hello", parse_mode="HTML")
    mock_post.assert_called_once_with(
        "https://api.telegram.org/botmytoken/sendMessage",
        json={"chat_id": "mychat", "text": "hello", "parse_mode": "HTML"},
        timeout=10,
    )


def test_send_message_prints_warning_on_http_error(capsys):
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 400
    mock_resp.text = "Bad Request"
    with patch("utils.telegram_client.requests.post", return_value=mock_resp):
        from utils.telegram_client import send_message
        send_message("tok", "chat", "msg")
    assert "Telegram error" in capsys.readouterr().out
