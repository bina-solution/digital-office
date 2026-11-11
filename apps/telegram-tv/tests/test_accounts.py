"""telegram-tv's accounts are Telegram USER logins only (DGO-1798): the vault's `telegram_*` also holds the telegram
app's bot tokens, which the settings card must never offer to switch to or remove."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import accounts  # noqa: E402


def test_only_user_logins_are_accounts(monkeypatch):
    monkeypatch.setattr(accounts, "_instances", lambda: ([
        {"id": "u1", "protocol": "telegram_user"},
        {"id": "b1", "protocol": "telegram_bot"},
        {"id": "u2", "protocol": "telegram_user"},
    ], None))
    insts, err = accounts.list_instances()
    assert [i["id"] for i in insts] == ["u1", "u2"] and err is None


def test_a_vault_that_does_not_answer_says_so(monkeypatch):
    monkeypatch.setattr(accounts, "_instances", lambda: ([], "שירות החשבונות אינו זמין"))
    assert accounts.list_instances() == ([], "שירות החשבונות אינו זמין")
