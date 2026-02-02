#!/usr/bin/env python3
"""Verify CPX secure hash calculation"""
import hashlib

# The SFWID from the URL
ext_user_id = "697f57038bf3c084d9f5c39f"
expected_hash = "922f62f86a3aab8686ce0da17b98c38b"

# The hash key from vm_settings.json
cpx_hash_key = "7PaLatMtNkJEtPaLE5J3WucLbkRKTGGW"
print(f"CPX_HASH_KEY: {cpx_hash_key}")

# Compute hash the way we're doing it
hash_input = f"{ext_user_id}-{cpx_hash_key}"
computed_hash = hashlib.md5(hash_input.encode()).hexdigest()

print(f"Hash input: {hash_input}")
print(f"Computed hash: {computed_hash}")
print(f"Expected hash: {expected_hash}")
print(f"Match: {computed_hash == expected_hash}")
