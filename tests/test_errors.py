from ralph_stack.errors import normalize_error, error_hash


def test_normalize_strips_paths_and_numbers():
    a = "File /home/mo/foo/bar.py line 42: TypeError: x is not defined"
    b = "File /tmp/abc/bar.py line 99: TypeError: x is not defined"
    assert normalize_error(a) == normalize_error(b)


def test_normalize_strips_hex_addresses():
    a = "object at 0x7f8a1b2c3d4e"
    b = "object at 0x1234567890ab"
    assert normalize_error(a) == normalize_error(b)


def test_error_hash_stable():
    assert error_hash("foo") == error_hash("foo")
    assert error_hash("foo") != error_hash("bar")
    assert len(error_hash("foo")) == 16
