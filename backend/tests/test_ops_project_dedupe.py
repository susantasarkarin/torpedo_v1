"""A won RFQ links to the Operations project the study already has."""
from app.services.won_handoff import client_key, find_existing_ops_project, study_key


def test_study_key_ignores_rfq_codes_vendor_suffix_and_punctuation():
    assert study_key("RFQ_Artha_iDirect Barrier_HRG_SFW") == study_key("Artha iDirect Barrier")
    assert study_key("RFQ_Eduventure 2.0_HRG_SFW") == study_key("Eduventure 2.0 - Lucid_new")
    # a new wave is a new project
    assert study_key("RFQ_Eduventure 2.0_Wave 6_HRG_SFW") != study_key("RFQ_Eduventure 2.0_HRG_SFW")
    # a title after " - " is kept when nothing else is left
    assert study_key("RFQ - Alzheimer's disease, dementia") == "alzheimer s disease dementia"
    assert study_key("RFQ") == ""
    assert study_key("Nicotine pouch") != study_key("Health Insurance Cues 2026")


def test_client_key_uses_the_company_part():
    assert client_key("Hansa - Cheetah") == client_key("Hansa")
    assert client_key("Hansa Research Group") != client_key("Ipsos UK")


class _Col:
    def __init__(self, docs):
        self.docs = docs

    def find_one(self, q, p=None):
        return next((d for d in self.docs if d.get("opportunity_id") == q.get("opportunity_id")), None)

    def find(self, q, p=None):
        return [d for d in self.docs if not d.get("is_deleted")]


def test_existing_manual_project_is_found_for_a_won_rfq():
    col = _Col([{"_id": 1, "projectName": "Artha iDirect Barrier", "client": "Hansa Research Group"},
                {"_id": 2, "projectName": "Percept Advertising", "client": "Hansa Research Group"}])
    hit = find_existing_ops_project(col, "RFQ_Artha_iDirect Barrier_HRG_SFW", "Hansa Research Group", "opp-9")
    assert hit["_id"] == 1
    assert find_existing_ops_project(col, "Brand New Study", "Hansa Research Group", "opp-9") is None
    assert find_existing_ops_project(col, "Artha iDirect Barrier", "Ipsos UK", "opp-9") is None
