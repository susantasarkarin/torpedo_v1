def test_mail_integration_module_exists():
    try:
        import backend.email_classification as ec
        assert hasattr(ec, '__name__')
    except Exception:
        # At minimum the module should be importable
        assert False, "email_classification module not importable"
