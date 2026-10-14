import pytest

from prancha.core.timefmt import TimeParseError, format_time, parse_time


def test_format_truncates_never_rounds_up():
    assert format_time(10.999) == "00:00:10"
    assert format_time(10.999, True) == "00:00:10.999"
    assert format_time(3661.5) == "01:01:01"
    assert format_time(9.9999999999, True) == "00:00:10.000"  # tolerância de ponto flutuante
    assert format_time(None) == "indisponível"


@pytest.mark.parametrize("text,expected", [
    ("00:01:30", 90), ("1:30", 90), ("90", 90), ("12,5", 12.5), ("00:00:10.250", 10.25), ("01:00:00", 3600),
])
def test_parse(text, expected):
    assert parse_time(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["abc", "00:61:00", "1:75", "", "-5"])
def test_parse_invalid(text):
    with pytest.raises(TimeParseError):
        parse_time(text)
