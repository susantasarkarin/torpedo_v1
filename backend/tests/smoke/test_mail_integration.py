import pytest

# Requires a RUNNING server on BASE_URL — these drive the live HTTP surface,
# not the code in-process. Marked so CI can run everything else (TOR-14):
#     pytest backend/tests -m "not smoke"
pytestmark = pytest.mark.smoke

def test_mail_integration_module_exists():
    try:
        import backend.email_classification as ec
        assert hasattr(ec, '__name__')
    except Exception:
        # At minimum the module should be importable
        assert False, "email_classification module not importable"
