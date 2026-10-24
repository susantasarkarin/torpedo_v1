"""Same person at a new company is one record; namesakes are not merged."""

from datetime import datetime

from scripts.merge_moved_people import plan, person_key


def lead(_id, email, name, **kw):
    return {"_id": _id, "email": email, "name": name, "updated_at": datetime(2026, 1, _id), **kw}


def test_moved_person_keeps_the_contact():
    pairs = plan([
        lead(1, "ramiz.jasnaik@ipsos.com", "ramiz jasnaik", source="csv_import"),
        lead(2, "ramiz.jasnaik@hansaresearch.com", "Ramiz Jasnaik | Hansa Research Group",
             source="gmail", stage="won"),
    ])
    assert [(old["_id"], keep["_id"]) for old, keep in pairs] == [(1, 2)]


def test_common_namesakes_are_left_alone():
    people = [lead(i, f"amit.singh@co{i}.com", "Amit Singh") for i in (1, 2)]
    # four other people share both words, so neither identifies anyone
    people += [lead(10 + i, f"person{i}@a.com", n) for i, n in enumerate(
        ["Amit Kumar", "Amit Shah", "Amit Rao", "Amit Jain", "Ravi Singh", "Raj Singh", "Om Singh", "Jai Singh"])]
    assert plan(people) == []


def test_weak_keys_never_match():
    assert person_key({"email": "info@a.com", "name": "Info Desk"}) is None
    assert person_key({"email": "ramiz.jasnaik@a.com", "name": "Ramiz"}) is None
    assert person_key({"email": "jasnaik, ramiz <x>", "name": "x"}) is None


def test_same_address_twice_is_not_a_move():
    assert plan([lead(1, "ramiz.jasnaik@a.com", "Ramiz Jasnaik"),
                 lead(2, "ramiz.jasnaik@a.com", "Ramiz Jasnaik")]) == []
