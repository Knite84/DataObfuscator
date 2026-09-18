from app.pass1_regex import SSN, EMAIL, IBAN, PHONE, URL, find


def test_email_and_url():
    text = "Email me at jane.doe@example.com or visit https://example.com/docs now."
    hits = find(text)
    cats = {h["category"] for h in hits}
    assert "email" in cats
    assert "url" in cats
    assert EMAIL.search(text).span() == (12, 32)


def test_phone_and_ssn():
    text = "Call (555) 123-4567. SSN 123-45-6789."
    hits = find(text)
    cats = {h["category"] for h in hits}
    assert "phone" in cats
    assert "national_id" in cats
    assert SSN.search(text).group() == "123-45-6789"


def test_credit_card_and_iban():
    text = "Card 4111 1111 1111 1111, DE89 3704 0044 0532 0130 00."
    cats = {h["category"] for h in find(text)}
    assert "financial" in cats
    assert "account_id" in cats


def test_offsets_valid_and_sorted():
    text = "jane@example.com called from +1 555 123 4567 about www.example.com."
    hits = find(text)
    for h in hits:
        assert h["quote"] == text[h["start"] : h["end"]]
    assert hits == sorted(hits, key=lambda h: (h["start"], -(h["end"] - h["start"])))
    assert URL.search(text) is not None
    assert PHONE.search(text) is not None
