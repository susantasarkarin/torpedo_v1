import { Link } from "react-router-dom";
import { RFQ_PAGE_HREF, rfqOf, rfqCandidatesOf, rfqStageLabel, rfqStageTone } from "./opsUtils";

// Compact RFQ match for a project row or header.
// Matched: stage-coloured chip linking to the sales RFQ list.
// Ambiguous (no match, candidates exist): amber "Review (N)" button, calls onReview.
// Unmatched: an em dash.
export default function RfqChip({ project, onReview }) {
  const rfq = rfqOf(project);
  if (rfq) {
    const title = rfq.title || rfq.id;
    return (
      <Link
        to={RFQ_PAGE_HREF}
        className={`ops-rfq-chip ops-rfq-chip--${rfqStageTone(rfq.stage)}`}
        title={`${title} (${rfqStageLabel(rfq.stage)}). Opens the RFQ list.`}
      >
        <span className="ops-rfq-chip__text">{title}</span>
      </Link>
    );
  }

  const count = rfqCandidatesOf(project).length;
  if (count > 0 && onReview) {
    return (
      <button
        type="button"
        className="ops-rfq-chip ops-rfq-chip--review"
        onClick={onReview}
        aria-label={`${count} possible RFQ matches. Review and link one.`}
        title="Several RFQs could match this project. Choose one."
      >
        Review ({count})
      </button>
    );
  }

  // Unmatched: a visible way to link one (owner 2026-11-18), a dash when read-only.
  if (onReview) {
    return (
      <button
        type="button"
        className="ops-rfq-chip ops-rfq-chip--review"
        onClick={onReview}
        title="No RFQ linked. Search and link the RFQ for this project."
      >
        + Link RFQ
      </button>
    );
  }
  return (
    <span className="ops-null" title="No RFQ linked" aria-label="No RFQ linked">
      —
    </span>
  );
}
