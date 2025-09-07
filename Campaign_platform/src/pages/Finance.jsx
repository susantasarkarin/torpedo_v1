function Finance() {
  const financeMetrics = [
    { title: "Monthly Revenue", value: "$127,450", change: "+8.2% from last month" },
    { title: "Total Expenses", value: "$89,230", change: "-3.1% from last month" },
    { title: "Net Profit", value: "$38,220", change: "+15.7% from last month" },
    { title: "Outstanding Invoices", value: "23", change: "5 overdue" },
  ]

  const recentTransactions = [
    {
      id: 1,
      description: "Email Campaign Platform License",
      amount: "-$299.00",
      date: "2024-01-16",
      status: "Completed",
    },
    { id: 2, description: "Client Payment - TechCorp", amount: "+$5,500.00", date: "2024-01-15", status: "Completed" },
    { id: 3, description: "Marketing Tools Subscription", amount: "-$149.00", date: "2024-01-14", status: "Completed" },
    { id: 4, description: "Client Payment - StartupXYZ", amount: "+$2,800.00", date: "2024-01-13", status: "Pending" },
  ]

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Finance Dashboard</h2>
          <p className="card-description">Monitor financial performance, expenses, and revenue streams.</p>
        </div>

        <div className="grid grid-cols-2 mb-6">
          {financeMetrics.map((metric, index) => (
            <div key={index} className="card">
              <h3 className="card-title">{metric.title}</h3>
              <p
                style={{
                  fontSize: "2rem",
                  fontWeight: "bold",
                  color: metric.value.includes("+") ? "#10b981" : metric.value.includes("-") ? "#ef4444" : "#3b82f6",
                  marginBottom: "0.5rem",
                }}
              >
                {metric.value}
              </p>
              <p style={{ fontSize: "0.875rem", color: "#6b7280" }}>{metric.change}</p>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-2">
          <div className="card">
            <h3 className="card-title">Recent Transactions</h3>
            <div style={{ marginTop: "1rem" }}>
              {recentTransactions.map((transaction) => (
                <div
                  key={transaction.id}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "0.75rem 0",
                    borderBottom: "1px solid #f3f4f6",
                  }}
                >
                  <div>
                    <p style={{ fontWeight: "500", marginBottom: "0.25rem" }}>{transaction.description}</p>
                    <p style={{ fontSize: "0.75rem", color: "#6b7280" }}>{transaction.date}</p>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <p
                      style={{
                        fontWeight: "600",
                        color: transaction.amount.includes("+") ? "#10b981" : "#ef4444",
                        marginBottom: "0.25rem",
                      }}
                    >
                      {transaction.amount}
                    </p>
                    <span
                      style={{
                        fontSize: "0.75rem",
                        padding: "0.125rem 0.5rem",
                        borderRadius: "9999px",
                        backgroundColor: transaction.status === "Completed" ? "#dcfce7" : "#fef3c7",
                        color: transaction.status === "Completed" ? "#166534" : "#92400e",
                      }}
                    >
                      {transaction.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <h3 className="card-title">Quick Actions</h3>
            <div className="grid" style={{ gap: "1rem", marginTop: "1rem" }}>
              <button className="btn btn-primary">Create Invoice</button>
              <button className="btn btn-secondary">Record Expense</button>
              <button className="btn btn-outline">Generate Report</button>
              <button className="btn btn-outline">View Budget</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Finance
