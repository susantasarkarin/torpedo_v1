import pytest
from auth import hash_password, verify_password, needs_rehash


def test_hash_and_verify():
    pwd = "Abcdef12"
    hashed = hash_password(pwd)
    assert hashed is not None
    assert verify_password(pwd, hashed) is True
    assert needs_rehash(hashed) in (True, False)
