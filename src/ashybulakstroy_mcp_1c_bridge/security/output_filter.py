from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .models import OutputPolicy


class OutputFilter:
    CREDENTIAL_KEYS = {"password", "secret", "token", "api_key", "apikey", "authorization", "bearer", "credential"}
    URL_KEYS = {"url", "endpoint", "webhook", "callback", "link"}
    EXTERNAL_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
    IIN_BIN_RE = re.compile(r"(?<!\d)(\d{12})(?!\d)")
    BANK_ACCOUNT_RE = re.compile(r"(?<!\d)(\d{20})(?!\d)")

    def __init__(self, policy: OutputPolicy):
        self.policy = policy

    def apply(self, payload: Any) -> Any:
        data = deepcopy(payload)
        return self._sanitize(data, key_hint=None)

    def _sanitize(self, value: Any, key_hint: str | None) -> Any:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if self.policy.redact_credentials and self._looks_like_credential_key(lowered):
                    out[key] = "[redacted-credential]"
                    continue
                out[key] = self._sanitize(item, key_hint=lowered)
            return out

        if isinstance(value, list):
            limited = value
            if key_hint in {"data", "rows"} and len(value) > self.policy.max_rows:
                limited = value[: self.policy.max_rows]
            return [self._sanitize(item, key_hint=key_hint) for item in limited]

        if isinstance(value, str):
            text = value
            if self.policy.redact_credentials and self._looks_like_credential_value(text, key_hint):
                return "[redacted-credential]"
            if self.policy.block_external_urls and self._looks_like_url_field(key_hint) and self.EXTERNAL_URL_RE.search(text):
                return "[blocked-external-url]"
            if self.policy.mask_iin_bin:
                text = self.IIN_BIN_RE.sub(self._mask_iin_bin, text)
            if self.policy.mask_bank_accounts:
                text = self.BANK_ACCOUNT_RE.sub(self._mask_bank_account, text)
            return text

        return value

    @classmethod
    def _looks_like_credential_key(cls, key: str) -> bool:
        return any(token in key for token in cls.CREDENTIAL_KEYS)

    @classmethod
    def _looks_like_url_field(cls, key: str | None) -> bool:
        if not key:
            return False
        return any(token in key for token in cls.URL_KEYS)

    @classmethod
    def _looks_like_credential_value(cls, value: str, key_hint: str | None) -> bool:
        if key_hint and cls._looks_like_credential_key(key_hint):
            return True
        lowered = value.lower()
        return lowered.startswith("bearer ") or "password=" in lowered or "token=" in lowered

    @staticmethod
    def _mask_iin_bin(match: re.Match[str]) -> str:
        value = match.group(1)
        return f"{value[:4]}****{value[-4:]}"

    @staticmethod
    def _mask_bank_account(match: re.Match[str]) -> str:
        value = match.group(1)
        return f"{value[:4]}************{value[-4:]}"
