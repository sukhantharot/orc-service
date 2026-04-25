from app.mrz import parse_td3
from app.scanners.passport import scan_passport_from_text


# Real-format synthetic TD3 from ICAO 9303 examples
LINE1 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<"
LINE2 = "L898902C36UTO7408122F1204159ZE184226B<<<<<10"


def test_parse_td3_extracts_fields():
    p = parse_td3(LINE1, LINE2)
    assert p is not None
    assert p.surname == "ERIKSSON"
    assert p.given_names == "ANNA MARIA"
    assert p.document_number == "L898902C3"
    assert p.nationality == "UTO"
    assert p.date_of_birth_iso == "1974-08-12"
    assert p.sex == "F"


def test_parse_td3_valid_check_digits():
    p = parse_td3(LINE1, LINE2)
    assert p is not None
    assert p.valid is True


def test_parse_td3_rejects_wrong_length():
    assert parse_td3("P<", LINE2) is None
    assert parse_td3(LINE1, "X<") is None


def test_parse_td3_requires_passport_marker():
    swapped = "I" + LINE1[1:]
    assert parse_td3(swapped, LINE2) is None


def test_parse_td3_tampered_doc_number_marks_invalid():
    tampered = "L898902C46UTO7408122F1204159ZE184226B<<<<<10"
    p = parse_td3(LINE1, tampered)
    assert p is not None
    assert p.valid is False


def test_scan_passport_from_text_happy_path():
    raw = LINE1 + "\n" + LINE2
    result, err = scan_passport_from_text(raw)
    assert err is None
    assert result is not None
    assert result.first_name == "ANNA MARIA"
    assert result.last_name == "ERIKSSON"
    assert result.document_number == "L898902C3"
    assert result.country == "UTO"
    assert result.sex.value == "F"
    assert result.document_valid is True


def test_scan_passport_from_text_no_mrz_returns_error():
    result, err = scan_passport_from_text("not an mrz at all\nnope")
    assert result is None
    assert err is not None
    assert err.code == "no_document_detected"
    assert err.detected_type is None
