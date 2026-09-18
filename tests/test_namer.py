from app.namer import replacement_for


def test_deterministic_across_categories():
    assert replacement_for("person", "John Smith") == replacement_for("person", "John Smith")
    assert replacement_for("email", "jane@x.com") == replacement_for("email", "jane@x.com")
    assert replacement_for("phone", "(555) 123-4567") == replacement_for("phone", "(555) 123-4567")


def test_different_sources_different_personnel():
    seen = {replacement_for("person", f"Person {i}") for i in range(40)}
    assert len(seen) > 20


def test_person_is_two_names():
    assert len(replacement_for("person", "John Smith").split()) == 2


def test_phone_fictional_range():
    phone = replacement_for("phone", "whatever")
    assert phone.startswith("(555) ")
    digits = phone.replace("(555) ", "").replace("-", "")
    assert len(digits) == 7


def test_national_id_ssa_never_issued_prefix():
    nid = replacement_for("national_id", "123-45-6789")
    assert nid.startswith("9")


def test_financial_16_digits():
    card = replacement_for("financial", "1111 2222 3333 4444").replace(" ", "")
    assert len(card) == 16

    def luhn_full_valid(s):
        total = 0
        for i, d in enumerate(reversed(s)):
            v = int(d)
            if i % 2 == 1:
                v *= 2
                if v > 9:
                    v -= 9
            total += v
        return total % 10 == 0

    assert luhn_full_valid(card)


def test_fallback_treated_as_person():
    assert replacement_for("whatever", "zzz") == replacement_for("person", "zzz")
