from app.intent import classify


def test_common_phrases():
    # นำร่องอำเภอกันทรลักษ์ 4 หมวด
    cases = {
        "หาช่างตัดหญ้าหน่อยครับ": "gardening",
        "แอร์ไม่เย็นเลย": "ac-cleaning",
        "อยากได้แม่บ้านทำความสะอาด": "housekeeping",
        "หญ้ารกมากช่วยมาดายหญ้าที": "gardening",
        "ล้างแอร์บ้านหน่อย": "ac-cleaning",
        "ต้องการคนมาทำความสะอาดบ้าน": "housekeeping",
        "เร่งด่วนมากมาตอนนี้เลยได้ไหม": "emergency",
    }
    for text, expected in cases.items():
        r = classify(text)
        assert r.confident, f"ควรมั่นใจ: {text} → {r}"
        assert r.slug == expected, f"{text}: ได้ {r.slug} คาด {expected}"


def test_unknown_text_asks_back():
    for text in ["สวัสดีครับ", "ราคาเท่าไหร่", "อยากหางานทำ"]:
        r = classify(text)
        assert not r.confident, f"ไม่ควรมั่นใจ: {text} → {r}"


def test_spaces_ignored():
    assert classify("ตัด หญ้า").slug == "gardening"
