from backend.app.models.crm_objects import Account, Contact, Lead


def test_account_model():
    a = Account(name="Acme Corp", email="info@acme.com")
    assert a.name == "Acme Corp"
    assert a.email == "info@acme.com"


def test_contact_model():
    c = Contact(email="joe@example.com", firstName="Joe")
    assert c.email == "joe@example.com"


def test_lead_model():
    l = Lead(email="lead@example.com", firstName="Lead")
    assert l.status == "new"
