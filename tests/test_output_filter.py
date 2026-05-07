from ashybulakstroy_mcp_1c_bridge.security import OutputFilter, OutputPolicy


def test_output_filter_limits_rows_in_data_and_rows():
    filter_ = OutputFilter(OutputPolicy(max_rows=2))

    payload = {
        "ok": True,
        "data": [{"id": 1}, {"id": 2}, {"id": 3}],
        "rows": [{"n": "a"}, {"n": "b"}, {"n": "c"}],
    }

    filtered = filter_.apply(payload)

    assert len(filtered["data"]) == 2
    assert len(filtered["rows"]) == 2
    assert filtered["data"][0]["id"] == 1
    assert filtered["rows"][1]["n"] == "b"


def test_output_filter_masks_iin_bin_and_bank_accounts_and_credentials():
    filter_ = OutputFilter(
        OutputPolicy(
            max_rows=100,
            mask_iin_bin=True,
            mask_bank_accounts=True,
            redact_credentials=True,
        )
    )

    payload = {
        "iin": "123456789012",
        "bin_text": "BIN 987654321098",
        "bank_account": "KZ 12345678901234567890",
        "password": "super-secret",
        "token": "Bearer abc123",
    }

    filtered = filter_.apply(payload)

    assert filtered["iin"] == "1234****9012"
    assert filtered["bin_text"] == "BIN 9876****1098"
    assert "************" in filtered["bank_account"]
    assert filtered["password"] == "[redacted-credential]"
    assert filtered["token"] == "[redacted-credential]"


def test_output_filter_blocks_external_urls_in_payload_like_fields():
    filter_ = OutputFilter(OutputPolicy(block_external_urls=True))

    payload = {
        "webhook_url": "https://evil.example.com/hook",
        "callback_endpoint": "http://example.org/callback",
        "note": "plain text with https://example.com should stay as text",
    }

    filtered = filter_.apply(payload)

    assert filtered["webhook_url"] == "[blocked-external-url]"
    assert filtered["callback_endpoint"] == "[blocked-external-url]"
    assert filtered["note"] == "plain text with https://example.com should stay as text"
