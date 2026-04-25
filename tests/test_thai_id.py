from datetime import date

from app.scanners.thai_id import (
    OcrLine,
    extract_dob,
    extract_first_name,
    extract_id_number,
    extract_last_name,
    extract_sex,
    scan_thai_id_from_lines,
)
from app.schemas import DocumentType, Sex
from app.validators import thai_id_checksum


def _valid_id() -> str:
    base = "110170015764"
    total = sum(int(base[i]) * (13 - i) for i in range(12))
    check = (11 - (total % 11)) % 10
    return base + str(check)


def _invalid_id() -> str:
    valid = _valid_id()
    wrong = (int(valid[-1]) + 1) % 10
    return valid[:-1] + str(wrong)


# --- ID number ---

def test_extract_id_number_strips_separators_and_validates():
    valid = _valid_id()
    spaced = f"{valid[0]} {valid[1:5]} {valid[5:10]} {valid[10:12]} {valid[12]}"
    id_str, conf, ok = extract_id_number([OcrLine(text=spaced, confidence=0.95)])
    assert id_str == valid
    assert ok is True
    assert conf == 0.95


def test_extract_id_number_prefers_checksum_valid_over_invalid():
    valid = _valid_id()
    invalid = _invalid_id()
    lines = [
        OcrLine(text=invalid, confidence=0.99),  # higher confidence but bad checksum
        OcrLine(text=valid, confidence=0.7),
    ]
    id_str, _, ok = extract_id_number(lines)
    assert id_str == valid
    assert ok is True


def test_extract_id_number_falls_back_to_invalid_checksum():
    invalid = _invalid_id()
    id_str, _, ok = extract_id_number([OcrLine(text=invalid, confidence=0.9)])
    assert id_str == invalid
    assert ok is False


def test_extract_id_number_returns_none_when_no_13_digit_run():
    id_str, conf, ok = extract_id_number([OcrLine(text="hello world", confidence=0.9)])
    assert id_str is None
    assert conf == 0.0
    assert ok is False


# --- Sex ---

def test_extract_sex_for_each_thai_title():
    assert extract_sex([OcrLine(text="นาย JOHN", confidence=0.9)])[0] == Sex.M
    assert extract_sex([OcrLine(text="นาง JANE", confidence=0.9)])[0] == Sex.F
    assert extract_sex([OcrLine(text="นางสาว JANE", confidence=0.9)])[0] == Sex.F
    assert extract_sex([OcrLine(text="เด็กชาย Bobby", confidence=0.9)])[0] == Sex.M
    assert extract_sex([OcrLine(text="เด็กหญิง Susie", confidence=0.9)])[0] == Sex.F


def test_extract_sex_returns_none_when_no_prefix():
    sex, conf = extract_sex([OcrLine(text="JOHN DOE", confidence=0.9)])
    assert sex is None
    assert conf == 0.0


def test_extract_sex_does_not_misclassify_นางสาว_as_นาง():
    # "นางสาว" contains "นาง" but should resolve to F via นางสาว — both are F so the value is fine,
    # but we want to make sure the longer prefix is matched first (regression guard).
    sex, _ = extract_sex([OcrLine(text="นางสาว SOMSRI", confidence=0.9)])
    assert sex == Sex.F


# --- Names ---

def test_extract_first_name_from_english_title():
    name, conf = extract_first_name([OcrLine(text="Mr. JOHN", confidence=0.88)])
    assert name == "JOHN"
    assert conf == 0.88


def test_extract_first_name_anchor_below():
    lines = [
        OcrLine(text="Name", confidence=0.95, cx=100, cy=50),
        OcrLine(text="Mr. SOMCHAI", confidence=0.9, cx=110, cy=80),
        OcrLine(text="Last name", confidence=0.95, cx=100, cy=120),
        OcrLine(text="JAIDEE", confidence=0.92, cx=110, cy=150),
    ]
    name, _ = extract_first_name(lines)
    assert name == "SOMCHAI"


def test_extract_first_name_anchor_inline():
    name, _ = extract_first_name([OcrLine(text="Name SOMCHAI", confidence=0.9)])
    assert name == "SOMCHAI"


def test_extract_last_name_anchor_below():
    lines = [
        OcrLine(text="Last name", confidence=0.95, cx=100, cy=120),
        OcrLine(text="JAIDEE", confidence=0.92, cx=110, cy=150),
    ]
    name, _ = extract_last_name(lines)
    assert name == "JAIDEE"


def test_extract_last_name_inline():
    name, _ = extract_last_name([OcrLine(text="Last name : JAIDEE", confidence=0.9)])
    assert name == "JAIDEE"


def test_extract_first_name_returns_none_when_absent():
    name, conf = extract_first_name([OcrLine(text="Identification", confidence=0.9)])
    assert name is None
    assert conf == 0.0


# --- DOB ---

def test_extract_dob_english_format():
    d, conf = extract_dob([OcrLine(text="Date of Birth 1 Jan. 1990", confidence=0.9)])
    assert d == date(1990, 1, 1)
    assert conf == 0.9


def test_extract_dob_thai_be_format_converts_to_ce():
    d, _ = extract_dob([OcrLine(text="1 ม.ค. 2533", confidence=0.9)])
    assert d == date(1990, 1, 1)


def test_extract_dob_thai_full_month():
    d, _ = extract_dob([OcrLine(text="15 มีนาคม 2533", confidence=0.9)])
    assert d == date(1990, 3, 15)


def test_extract_dob_rejects_future_date():
    d, conf = extract_dob([OcrLine(text="1 Jan. 2999", confidence=0.9)])
    assert d is None
    assert conf == 0.0


def test_extract_dob_returns_none_when_no_date():
    d, conf = extract_dob([OcrLine(text="JOHN DOE", confidence=0.9)])
    assert d is None
    assert conf == 0.0


# --- Orchestration ---

def test_scan_thai_id_from_lines_happy_path():
    valid = _valid_id()
    lines = [
        OcrLine(text=valid, confidence=0.95),
        OcrLine(text="นาย SOMCHAI", confidence=0.9, cx=100, cy=50),
        OcrLine(text="Name SOMCHAI", confidence=0.9, cx=100, cy=80),
        OcrLine(text="Last name JAIDEE", confidence=0.92, cx=100, cy=120),
        OcrLine(text="Date of Birth 1 Jan. 1990", confidence=0.88),
    ]
    result, err = scan_thai_id_from_lines(lines)
    assert err is None
    assert result is not None
    assert result.type == DocumentType.THAI_ID
    assert result.document_number == valid
    assert result.first_name == "SOMCHAI"
    assert result.last_name == "JAIDEE"
    assert result.date_of_birth == date(1990, 1, 1)
    assert result.sex == Sex.M
    assert result.country == "THA"
    assert result.document_valid is True
    assert result.confidence.country == 1.0
    assert result.confidence.overall > 0.8
    assert result.warnings == []


def test_scan_thai_id_from_lines_no_id_returns_no_document():
    result, err = scan_thai_id_from_lines([OcrLine(text="hello", confidence=0.9)])
    assert result is None
    assert err is not None
    assert err.code == "no_document_detected"
    assert err.detected_type is None


def test_scan_thai_id_from_lines_invalid_checksum_warns():
    invalid = _invalid_id()
    lines = [OcrLine(text=invalid, confidence=0.95)]
    result, err = scan_thai_id_from_lines(lines)
    assert err is None
    assert result is not None
    assert result.document_valid is False
    assert "thai_id_checksum_failed" in result.warnings


def test_scan_thai_id_from_lines_partial_extraction_returns_nulls():
    valid = _valid_id()
    lines = [OcrLine(text=valid, confidence=0.95)]
    result, err = scan_thai_id_from_lines(lines)
    assert err is None
    assert result is not None
    assert result.first_name is None
    assert result.last_name is None
    assert result.sex is None
    assert result.date_of_birth is None
    assert result.confidence.first_name == 0.0
    assert result.confidence.last_name == 0.0
    assert result.confidence.sex == 0.0
    assert result.confidence.date_of_birth == 0.0


def test_synthetic_id_helper_passes_checksum():
    """Sanity check on the test helper itself."""
    assert thai_id_checksum(_valid_id())
    assert not thai_id_checksum(_invalid_id())
