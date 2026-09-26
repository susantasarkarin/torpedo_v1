"""
FIT SIGNALS -- the title check that does not trust a model
==========================================================
See leads/fit_signals.py. These pin the term lists: titles that name a role we sell
to must be recognised, and ordinary non-fit titles must not be, since a false hit
only costs a human look but a missed one lets a model finally reject a good lead.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads.fit_signals import fit_signals, strongest_fit


@pytest.mark.parametrize("title,bucket", [
    # real titles the local 3B rejected at confidence 0.9 on 2026-09-20
    ("BIM Manager / Product Owner (integrations)", "BIM"),
    ("Director dpto. de Infraestructuras, BIM y Transformación Digital", "BIM"),
    ("Head, Research & Insights I India SA I", "SFW"),
    ("Research Director", "SFW"),
    ("VP, Research & Insights at FutureBrand", "SFW"),
    ("Senior Research Manager at Toluna ...", "SFW"),
    ("Chief Marketing Officer at Tourism Australia", "COGENTIX_RESEARCH"),
    ("Marketing Director", "COGENTIX_RESEARCH"),
    # the rest of the ideal-buyer lists in outreach_config.BUCKETS
    ("Head of BIM", "BIM"),
    ("CAD Manager", "BIM"),
    ("Dy. CAD Manager", "BIM"),
    ("VDC Coordinator", "BIM"),
    ("Panel Manager", "SFW"),
    ("Primary Research Manager", "SFW"),
    ("Market Research Manager - Chemicals", "SFW"),
    ("Director - Consumer Insights", "COGENTIX_RESEARCH"),
    ("Head of Brand", "COGENTIX_RESEARCH"),
    ("VP Marketing", "COGENTIX_RESEARCH"),
])
def test_ideal_buyer_titles_carry_their_signal(title, bucket):
    assert bucket in [b for b, _ in fit_signals(title)], title
    assert strongest_fit(title) is not None


@pytest.mark.parametrize("title", [
    "Chief Financial Officer",
    "Head of HR",
    "Global Head of HR DHL Supply Chain",
    "Sales Support",
    "General Manager",
    "Software Engineer",
    "Account Executive",
    "Director of Operations",
    "Supply Chain Manager",
    "",
    None,
])
def test_ordinary_titles_carry_no_signal(title):
    assert strongest_fit(title) is None


def test_matching_is_by_whole_word_not_substring():
    """'bim' inside another word, 'cad' inside 'cadence', 'panel' as in 'solar panelling'."""
    assert strongest_fit("Cadence Design Analyst") is None
    assert strongest_fit("Bimal Roy, Accountant") is None
    assert strongest_fit("Insightful Leader") is None


def test_a_title_can_carry_more_than_one_signal():
    buckets = {b for b, _ in fit_signals("Head of BIM and Market Research")}
    assert {"BIM", "SFW"} <= buckets


def test_case_is_ignored():
    assert strongest_fit("HEAD OF BIM") is not None
    assert strongest_fit("cmo") is not None
