from leads import query_feedback as qf

ICP = {"slug": "sfw", "designations": ["Marketing Manager", "Insights Director"], "industries": ["FMCG", "Retail"],
       "countries": ["India", "UAE"]}
CFG = dict(qf.DEFAULTS)


def test_qkey_ignores_exclusions_and_case():
    assert qf.qkey('"Marketing Manager" FMCG India -jobs -"free lance"') == '"marketing manager" fmcg india'


def test_apply_hints_adds_exclusions_and_drops_retired():
    hints = {"enabled": True, "exclude_terms": ["jobs", "student"], "retired": ['"Marketing Manager" FMCG India']}
    out = qf.apply_hints(['"Marketing Manager" FMCG India', '"Insights Director" Retail UAE'], hints)
    assert out == ['"Insights Director" Retail UAE -jobs -student']


def test_apply_hints_disabled_or_missing_changes_nothing():
    qs = ["a b", "c d"]
    assert qf.apply_hints(qs, None) == qs
    assert qf.apply_hints(qs, {"enabled": False, "exclude_terms": ["x"]}) == qs


def test_apply_hints_respects_max_length_and_does_not_double_add():
    hints = {"exclude_terms": ["aaaaaaaaaa"] * 1 + ["bbbbbbbbbb"]}
    q = "x" * 225
    out = qf.apply_hints([q + " -aaaaaaaaaa"], hints)[0]
    assert len(out) <= 240 and out.count("-aaaaaaaaaa") == 1


def test_seeds_go_first_but_never_repeat_used_queries():
    hints = {"seed_queries": ["good one", "used one", "good two"]}
    out = qf.merge_seeds(["new a", "new b", "new c", "new d"], hints, ["used one"], 4)
    assert out[:2] == ["good one", "good two"] and len(out) == 4 and "used one" not in out


def test_score_counts_only_judged_leads():
    runs = [{"query": "q1", "qkey": "q1", "found": 4, "urls": ["a", "b", "c", "d"]},
            {"query": "q1 -jobs", "qkey": "q1", "found": 1, "urls": ["e"]}]
    v = {"a": "SFW", "b": "REJECT", "c": "REVIEW", "e": "BIM"}
    s = qf.score_queries(runs, v)["q1"]
    assert (s["runs"], s["judged"], s["good"], s["junk"], s["good_rate"]) == (2, 3, 2, 1, 0.667)


def test_unjudged_query_has_no_rate():
    assert qf.score_queries([{"query": "q", "qkey": "q", "found": 1, "urls": ["z"]}], {})["q"]["good_rate"] is None


def test_refinement_check_rejects_icp_words_phrases_and_junk_terms():
    chk = qf.check_refinement(ICP, CFG)
    assert chk({"exclude_terms": ["jobs", "intern"]}, "") == []
    assert chk({"exclude_terms": ["marketing"]}, "")                       # part of the ICP
    assert chk({"exclude_terms": ["india"]}, "")                           # a target country
    assert chk({"exclude_terms": ["a very long phrase here"]}, "")
    assert chk({"exclude_terms": ["site:linkedin.com"]}, "")
    assert chk({"exclude_terms": [f"term{i}" for i in range(9)]}, "")


class _Col:
    def __init__(self, docs): self.docs = docs
    def find_one(self, q): return self.docs.get(q.get("_id"))


def test_run_cycle_skips_when_too_few_judged_leads(monkeypatch):
    class Col:
        def __init__(self, rows=None): self.rows = rows or []
        def find_one(self, *a, **k): return None
        def find(self, *a, **k): return list(self.rows)
    cols = {"icp_search_hints": Col(), "search_query_leads": Col([{"query": "q", "qkey": "q", "found": 1, "urls": ["u"]}]),
            "leads_enriched": Col(), "config": Col()}

    class DB:
        def __getitem__(self, k): return cols[k]
    gd = lambda name: DB()
    out = qf.run_cycle(gd=gd, icps=[ICP], apply=True)
    assert "only" in out[0]["skipped"]
