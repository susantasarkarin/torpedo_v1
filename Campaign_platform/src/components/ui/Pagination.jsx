import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react"

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100]

export default function Pagination({
  currentPage = 1,
  totalPages = 1,
  totalRecords = 0,
  pageSize = 100,
  onPageChange,
  onPageSizeChange,
  loading = false,
}) {
  const start = totalRecords === 0 ? 0 : (currentPage - 1) * pageSize + 1
  const end = Math.min(currentPage * pageSize, totalRecords)

  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 0", gap: 16, flexWrap: "wrap" }}>
      {/* Left: showing X-Y of Z */}
      <div style={{ fontSize: "0.85rem", color: "#64748b" }}>
        {totalRecords > 0 ? (
          <>Showing <strong>{start}</strong>–<strong>{end}</strong> of <strong>{totalRecords.toLocaleString()}</strong></>
        ) : (
          "No records"
        )}
      </div>

      {/* Center: page navigation */}
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <button
          disabled={currentPage <= 1 || loading}
          onClick={() => onPageChange(1)}
          style={btnStyle(currentPage <= 1 || loading)}
          title="First page"
        >
          <ChevronsLeft size={16} />
        </button>
        <button
          disabled={currentPage <= 1 || loading}
          onClick={() => onPageChange(currentPage - 1)}
          style={btnStyle(currentPage <= 1 || loading)}
          title="Previous page"
        >
          <ChevronLeft size={16} />
        </button>

        <span style={{ fontSize: "0.85rem", color: "#374151", padding: "0 8px", whiteSpace: "nowrap" }}>
          Page <strong>{currentPage}</strong> of <strong>{totalPages}</strong>
        </span>

        <button
          disabled={currentPage >= totalPages || loading}
          onClick={() => onPageChange(currentPage + 1)}
          style={btnStyle(currentPage >= totalPages || loading)}
          title="Next page"
        >
          <ChevronRight size={16} />
        </button>
        <button
          disabled={currentPage >= totalPages || loading}
          onClick={() => onPageChange(totalPages)}
          style={btnStyle(currentPage >= totalPages || loading)}
          title="Last page"
        >
          <ChevronsRight size={16} />
        </button>
      </div>

      {/* Right: records per page */}
      {onPageSizeChange && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.85rem", color: "#64748b" }}>
          <span>Rows:</span>
          <select
            value={pageSize}
            onChange={(e) => onPageSizeChange(Number(e.target.value))}
            disabled={loading}
            style={{
              padding: "4px 8px", borderRadius: 6, border: "1px solid #e2e8f0",
              background: "#fff", fontSize: "0.85rem", cursor: "pointer",
            }}
          >
            {PAGE_SIZE_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        </div>
      )}
    </div>
  )
}

function btnStyle(disabled) {
  return {
    padding: "6px 8px",
    borderRadius: 6,
    border: "1px solid #e2e8f0",
    background: "#fff",
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.4 : 1,
    display: "inline-flex",
    alignItems: "center",
  }
}
