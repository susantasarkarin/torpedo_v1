"""
CINT INTELLIGENCE AGENT (buyer performance scoring)

Deterministic, zero-AI/model scoring of Cint buyer (account_name) performance
from real, already-collected fields in cint_research.cint_surveys (157,023
documents as of 2026-09-17). Built the same way panel_intelligence_agent.py's
assess_panelist()/compute_engagement() were: a pure function over real fields,
no invented formula.

Real evidence behind this (live aggregation, 2026-09-17):
  - avg_conversion varies genuinely across named buyers: from 0.0037
    (OpinionSpark LLC) to 6.65 (Lucid Marketplace Services), with most
    buyers clustered well under 0.1 and a distinct smaller group above 1.5 --
    a real, natural gap, not an arbitrary line.
  - deactivation rate (deactivated surveys / total surveys) varies just as
    genuinely: SAGO has 13,577 of 16,925 surveys deactivated (80%), Kantar -
    CEX has 1,045 of 2,475 (42%).
  - `source_api` is 99%+ a single value (fulcrum_offerwall) across the whole
    collection -- not a useful axis to segment by today.
  - `deactivation_reason` is populated for only 12,942 of 75,222 inactive
    surveys (17%) and has exactly one distinct value observed
    ("not_on_offerwall") -- not rich enough yet to build a reason-level
    breakdown; noted as a real data-completeness gap, not built around.

Deliberately does NOT combine conversion and deactivation rate into one
weighted numeric score -- picking a weighting between them would be
inventing a business-policy judgment about which matters more, not reading
one from the data. Instead this returns a tier from the plain combination of
two independently-thresholded real signals, and callers can look at the two
raw numbers (`avg_conversion`, `deactivation_rate`) directly rather than
trust a single opaque score.

Scope of this pass: the pure scorer only, unit-tested and validated against
the real aggregation above. NOT yet wired into a live query/scheduled path,
NOT registered in app/services/ai_engine.py's agent registry, and not
connected to any action (no Cint API calls, no allocation changes) -- read-
only analysis capability only, per the established ordering. Wiring it into
a real per-buyer aggregation query and deciding whether/how to surface it
(a report? a recommend-mode task per underperforming buyer?) is a separate,
later increment.
"""

from typing import Any, Dict

# Real data shows a natural gap here (see module docstring) -- not a round
# number picked without basis.
HIGH_CONVERSION_THRESHOLD = 1.0     # percent; most buyers cluster well under 0.1
HIGH_DEACTIVATION_RATE = 0.5        # majority of this buyer's surveys got deactivated


def score_buyer_performance(
    surveys: int,
    avg_conversion: float,
    deactivated: int,
) -> Dict[str, Any]:
    """
    Pure. No I/O. Classifies a Cint buyer's (account_name) aggregate real
    performance into a descriptive tier.

    Tiers:
      - "no_data"        -- zero surveys on record
      - "strong"         -- conversion above threshold, deactivation rate not high
      - "underperforming" -- deactivation rate high, conversion not above threshold
      - "mixed"          -- both signals present (real conversion track record
                             AND a high deactivation rate) -- genuinely
                             ambiguous, not confidently good or bad
      - "average"        -- neither signal crosses its threshold
    """
    if surveys <= 0:
        return {"tier": "no_data", "deactivation_rate": None,
                "avg_conversion": avg_conversion}

    deactivation_rate = deactivated / surveys
    high_conversion = avg_conversion >= HIGH_CONVERSION_THRESHOLD
    high_deactivation = deactivation_rate >= HIGH_DEACTIVATION_RATE

    if high_conversion and high_deactivation:
        tier = "mixed"
    elif high_conversion:
        tier = "strong"
    elif high_deactivation:
        tier = "underperforming"
    else:
        tier = "average"

    return {
        "tier": tier,
        "deactivation_rate": round(deactivation_rate, 3),
        "avg_conversion": avg_conversion,
    }
