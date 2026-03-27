from aegis.utils.time import now_utc


def test_now_utc_is_timezone_aware():
    value = now_utc()
    assert value.tzinfo is not None
    assert value.utcoffset().total_seconds() == 0
