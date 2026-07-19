from app.promptpay import _crc16, payload


def test_payload_phone_structure():
    p = payload("0812345678", 350.0)
    assert p.startswith("000201")
    assert "010212" in p            # dynamic QR
    assert "A000000677010111" in p  # PromptPay AID
    assert "0066812345678" in p     # เบอร์แปลงเป็น 0066 + ตัดศูนย์
    assert "5303764" in p           # THB
    assert "5406350.00" in p        # จำนวนเงิน
    # CRC ท้าย payload ต้องตรงกับที่คำนวณใหม่
    assert p[-4:] == _crc16(p[:-4])


def test_payload_national_id():
    p = payload("1-2345-67890-12-3", None)
    assert "02131234567890123" in p
    assert "010211" in p            # static QR (ไม่ระบุยอด)
    assert "54" + "06" not in p[p.index("5303764"):p.index("5802TH")]


def test_crc_known_vector():
    # CRC-16/CCITT-FALSE ของ "123456789" คือ 0x29B1
    assert _crc16("123456789") == "29B1"
