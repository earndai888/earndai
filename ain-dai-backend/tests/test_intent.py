from app.intent import classify


def test_common_phrases():
    cases = {
        "หาช่างตัดหญ้าหน่อยครับ": "gardening",
        "แอร์ไม่เย็นเลย": "ac-cleaning",
        "ท่อน้ำแตกด่วน": "plumber",
        "ไฟดับทั้งบ้าน เบรกเกอร์ตก": "electrician",
        "อยากได้แม่บ้านทำความสะอาด": "housekeeping",
        "ย้ายบ้าน ต้องการรถกระบะขนของ": "transport",
        "หลังคารั่ว ฝนตกน้ำหยด": "handyman",
        "เครื่องซักผ้าเสีย": "appliance",
        "ส้วมตันครับ": "plumber",
        "หญ้ารกมากช่วยมาดายหญ้าที": "gardening",
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
