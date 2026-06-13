from __future__ import annotations

from src.privacy.audit import mask_pii, safe_log_query


class TestPIIMasking:
    def test_mask_email(self) -> None:
        text = "Contact alice@bevar.org for details"
        masked = mask_pii(text)
        assert "alice@bevar.org" not in masked
        assert "[EMAIL]" in masked

    def test_mask_phone(self) -> None:
        text = "Call +45 12 34 56 78"
        masked = mask_pii(text)
        assert "[PHONE]" in masked

    def test_mask_cpr(self) -> None:
        text = "CPR number: 150190-1234"
        masked = mask_pii(text)
        assert "150190-1234" not in masked

    def test_no_pii(self) -> None:
        text = "Just a regular query about grants"
        assert mask_pii(text) == text

    def test_safe_log_query(self) -> None:
        query = "find emails from alice@bevar.org"
        safe = safe_log_query(query)
        assert "alice@bevar.org" not in safe
