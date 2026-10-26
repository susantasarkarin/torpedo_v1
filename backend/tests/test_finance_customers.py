"""Finance customer names: one company name per account, never a person's."""
from backfill.finance_customers import company_name, is_person


def test_people_are_not_companies():
    for n in ("Wael RMR (Rmr Research)", "Teng, Josene (KWKAL) (Kantar)", "Garret McDannald", "Dragos Man"):
        assert is_person(n), n
    for n in ("Cint Exchange", "Hansa Research Group", "Qualtrics", "ProdegeMR", "Kadence International", "Netquest"):
        assert not is_person(n), n


def test_billed_name_then_account_then_bracketed_company():
    assert company_name(["Cint Exchange"], "Sheik Sikkander (Cint)", []) == "Cint Exchange"
    assert company_name(["Hansa Research Group Pvt Ltd"], "Hansa Research Group", []) == "Hansa Research Group Pvt Ltd"
    assert company_name([], "Garret McDannald", ["Meghna Subba (Toluna)"]) == "Toluna"
    assert company_name([], "Wael RMR (Rmr Research)", ["Rmr-Research"]) == "Rmr-Research"
    assert company_name(["Dragos Man"], "Mihaela Petre (Ipsos)", []) == "Ipsos"
