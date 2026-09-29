from app.services import email_structure as es


def test_owner_example():
    assert es.structure_of("susanta@cogentixresearch.com", "susanta", "sarkar") == ("{first_name}", "{first}")


def test_common_structures():
    assert es.structure_of("keya.kundu@hansaresearch.com", "keya", "kundu") == ("{first_name}.{last_name}", "{first}.{last}")
    assert es.structure_of("jhalder@luc.id", "jyoti", "halder") == ("{first_initial}{last_name}", "{f}{last}")
    assert es.structure_of("rohit.tiwari2@cint.com", "rohit", "tiwari")[0] == "{first_name}.{last_name}{digits}"
    assert es.structure_of("accountspayable@hansaresearch.com", "", "")[0] == "role:accountspayable"
    assert es.structure_of("xyz123@acme.com", "jane", "roe") == ("unknown", None)


def test_display_names_are_cleaned():
    assert es.split_name("Keya Kundu | Hansa Research Group (Hansaresearch)") == ("keya", "kundu")
    assert es.split_name("Chin, Alfred (Rakuten)") == ("alfred", "chin")
    assert es.split_name('"Susanta Sarkar" <susanta@cogentixresearch.com>') == ("susanta", "sarkar")
