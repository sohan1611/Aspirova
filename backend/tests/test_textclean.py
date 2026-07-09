from core.textclean import fix_text


def test_fix_text_repairs_latin1_utf8_mojibake() -> None:
    assert fix_text("SÃ£o Paulo") == "São Paulo"


def test_fix_text_repairs_double_encoded_cjk() -> None:
    mojibake = "北京市".encode().decode("latin-1").encode().decode("latin-1")
    assert fix_text(mojibake) == "北京市"


def test_fix_text_preserves_none_and_clean_text() -> None:
    assert fix_text(None) is None
    assert fix_text("Already clean") == "Already clean"


def test_fix_text_is_idempotent() -> None:
    value = "  Agudos,   SÃ£o Paulo, Brasil  "
    fixed = fix_text(value)
    assert fix_text(fixed) == fixed
