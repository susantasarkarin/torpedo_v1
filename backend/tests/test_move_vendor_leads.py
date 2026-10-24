"""Which Sales > Leads records are really vendors."""

from scripts.move_vendor_leads import vendor_verdict

PROTECTED = {"cint.com": "both", "hansaresearch.com": "client", "acmepanels.com": "vendor"}


def test_data_tools_and_banks_move_on_domain_alone():
    assert vendor_verdict({"email": "charles.knauft@zoominfo.com"}, [], PROTECTED) == (True, "service_domain")
    assert vendor_verdict({"email": "x@service.axisbankmail.com"}, [], PROTECTED) == (True, "service_domain")


def test_only_vendor_mail_moves():
    assert vendor_verdict({"email": "mohit.p@logicrays.com"}, ["vendor", "vendor"], PROTECTED) == (True, "vendor_mail_only")


def test_any_buyer_mail_keeps_the_lead():
    assert vendor_verdict({"email": "a@agency.com"}, ["vendor", "client"], PROTECTED) == (False, "has_buyer_mail")


def test_both_and_client_parties_never_move():
    assert vendor_verdict({"email": "sheik@cint.com"}, ["vendor"], PROTECTED) == (False, "relationship_both")
    assert vendor_verdict({"email": "k@hansaresearch.com"}, ["vendor"], PROTECTED) == (False, "relationship_client")


def test_named_vendor_moves():
    assert vendor_verdict({"email": "a@acmepanels.com"}, [], PROTECTED) == (True, "relationship_vendor")


def test_a_person_decision_wins():
    lead = {"email": "a@zoominfo.com", "lead_status_source": "human"}
    assert vendor_verdict(lead, ["vendor"], PROTECTED) == (False, "status_set_by_person")


def test_no_evidence_stays():
    assert vendor_verdict({"email": "a@quiet.com"}, [], PROTECTED) == (False, "no_mail_from_them")
