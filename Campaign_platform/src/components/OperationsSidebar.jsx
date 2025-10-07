"use client"

function OperationsSidebar() {
  return (
    <aside className="left-sidebar">
      <nav className="sidebar-menu">
        <ul>
          <li><a href="/operations/system">System Monitoring</a></li>
          <li><a href="/operations/projects">Projects</a></li>
          <li><a href="/operations/performance">Performance</a></li>
          <li><a href="/operations/efficiency">Efficiency</a></li>
        </ul>
      </nav>
    </aside>
  )
}

export default OperationsSidebar
