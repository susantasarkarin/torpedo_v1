// One navigation map for the whole admin app. It replaces the six section
// sidebars (Sales was on the right, the rest on the left) and the logo
// dropdown that switched between them; every link they had is here, with
// the same paths and the same "active" rules.
//
// item: { label, icon, to, exact?, also?: [paths that also make it active] }
// group: { label, items }

export const MODULES = [
  {
    key: "sales",
    label: "Sales",
    icon: "💼",
    root: "/admin/sales",
    groups: [
      {
        label: "Sales",
        items: [
          { label: "Sales Dashboard", icon: "📊", to: "/admin/sales", exact: true },
          { label: "Leads", icon: "👥", to: "/admin/sales/leads" },
          { label: "Contacts", icon: "📞", to: "/admin/sales/contacts" },
          { label: "Account", icon: "🏢", to: "/admin/sales/account" },
          { label: "RFQ", icon: "📋", to: "/admin/sales/rfq" },
        ],
      },
      {
        label: "Campaign",
        items: [
          { label: "AI Database", icon: "🤖", to: "/admin/sales/campaign/ai-leads" },
          { label: "Cold Outreach", icon: "📨", to: "/admin/sales/outreach" },
        ],
      },
      {
        label: "Automation",
        items: [
          {
            label: "AI Agent",
            icon: "🤖",
            to: "/admin/sales/agent-dashboard",
            also: ["/admin/sales/agent-settings", "/admin/sales/company-upload"],
          },
        ],
      },
    ],
  },
  {
    key: "marketing",
    label: "Marketing",
    icon: "📈",
    root: "/admin/marketing",
    groups: [
      {
        label: "Marketing",
        items: [
          { label: "Overview", icon: "🏠", to: "/admin/marketing", exact: true },
          { label: "Website CMS", icon: "🌐", to: "/admin/marketing/websites" },
          { label: "LinkedIn", icon: "💼", to: "/admin/marketing/linkedin" },
          { label: "Media Library", icon: "🖼️", to: "/admin/marketing/media" },
        ],
      },
    ],
  },
  {
    key: "finance",
    label: "Finance",
    icon: "💰",
    root: "/admin/finance",
    groups: [
      {
        label: "Finance",
        items: [
          { label: "Dashboard", icon: "📊", to: "/admin/finance", exact: true },
          { label: "Settings", icon: "⚙️", to: "/admin/finance/settings" },
        ],
      },
      {
        label: "Sales",
        items: [
          { label: "Customers", icon: "👥", to: "/admin/finance/customers" },
          { label: "Estimates", icon: "📝", to: "/admin/finance/estimates" },
          { label: "Invoices", icon: "📄", to: "/admin/finance/invoices" },
          { label: "Payments", icon: "💵", to: "/admin/finance/payments" },
        ],
      },
      {
        label: "Purchase",
        items: [
          { label: "Vendors", icon: "🏢", to: "/admin/finance/vendors" },
          { label: "Purchase Orders", icon: "📋", to: "/admin/finance/purchase-orders" },
          { label: "Bills", icon: "🧾", to: "/admin/finance/bills" },
          { label: "Expenses", icon: "💳", to: "/admin/finance/expenses" },
        ],
      },
      {
        label: "Reports",
        items: [
          { label: "Profit & Loss", icon: "📊", to: "/admin/finance/reports/profit-loss" },
          { label: "Balance Sheet", icon: "⚖️", to: "/admin/finance/reports/balance-sheet" },
          { label: "Cash Flow", icon: "💹", to: "/admin/finance/reports/cash-flow" },
          { label: "GST Reports", icon: "🧮", to: "/admin/finance/reports/gst" },
          { label: "Aging Reports", icon: "⏰", to: "/admin/finance/reports/aging" },
        ],
      },
    ],
  },
  {
    key: "operations",
    label: "Operations",
    icon: "⚙️",
    root: "/admin/operations",
    groups: [
      {
        label: "Operations",
        items: [
          {
            label: "Dashboard",
            icon: "📊",
            to: "/admin/operations/dashboard",
            exact: true,
            also: ["/admin/operations"],
          },
          { label: "Clients", icon: "👤", to: "/admin/operations/clients" },
          { label: "Vendors", icon: "🏢", to: "/admin/operations/vendors" },
          { label: "Projects", icon: "📂", to: "/admin/operations/projects" },
          { label: "Survey Pool", icon: "📋", to: "/admin/operations/survey-pool" },
          { label: "Potential Client", icon: "💼", to: "/admin/operations/potential-clients" },
          { label: "Rate Card", icon: "💵", to: "/admin/operations/rate-card" },
          { label: "Yield Management", icon: "📈", to: "/admin/operations/yield-management" },
          { label: "QRE", icon: "🔬", to: "/admin/operations/qre" },
          { label: "Survey Revenue", icon: "💰", to: "/admin/surveys/revenue" },
          { label: "System Logs", icon: "🧾", to: "/admin/logs" },
        ],
      },
      {
        label: "Traffic",
        items: [
          { label: "Inbound Traffic", icon: "📥", to: "/admin/operations/traffic" },
          { label: "Outbound Traffic", icon: "📤", to: "/admin/operations/reports" },
        ],
      },
    ],
  },
  {
    key: "vendor",
    label: "Vendors",
    icon: "🏢",
    root: "/admin/vendor",
    groups: [
      {
        label: "Vendors",
        items: [
          { label: "Dashboard", icon: "📊", to: "/admin/vendor", exact: true },
          { label: "Vendor Leads", icon: "👥", to: "/admin/vendor/leads" },
          { label: "Vendors", icon: "🏢", to: "/admin/vendor/all" },
          { label: "Billing", icon: "💰", to: "/admin/vendor/billing" },
          { label: "Payment", icon: "💳", to: "/admin/vendor/payments" },
          { label: "Reports", icon: "📈", to: "/admin/vendor/reports" },
        ],
      },
    ],
  },
  {
    key: "hr",
    label: "HR",
    icon: "👥",
    root: "/admin/hr",
    groups: [{ label: "HR", items: [{ label: "HR", icon: "👥", to: "/admin/hr" }] }],
  },
  {
    key: "panel-admin",
    label: "Panel",
    icon: "📋",
    root: "/admin/panel-admin",
    groups: [
      {
        label: "Panel",
        items: [
          {
            label: "Overview",
            icon: "📊",
            to: "/admin/panel-admin",
            exact: true,
            also: ["/admin/panel-admin/dashboard"],
          },
          { label: "Members", icon: "👥", to: "/admin/panel-admin/members" },
          { label: "Recruitment", icon: "📣", to: "/admin/panel-admin/recruitment" },
          { label: "Profiling & Quality", icon: "🧭", to: "/admin/panel-admin/profiling" },
          { label: "Rewards", icon: "🎁", to: "/admin/panel-admin/rewards" },
        ],
      },
    ],
  },
]

// the profile menu's links (was the top-right dropdown)
export const ACCOUNT_LINKS = [
  { label: "Command Centre", icon: "🧭", to: "/admin/command-centre" },
  { label: "Review Queue", icon: "✅", to: "/admin/review-queue" },
  { label: "My Profile", icon: "👤", to: "/admin/profile" },
  { label: "Settings", icon: "⚙️", to: "/admin/settings" },
  { label: "Mail Pool", icon: "📬", to: "/admin/mail-pool" },
  { label: "Gmail Settings", icon: "📧", to: "/admin/gmail-setup" },
  { label: "Help & Support", icon: "🛟", to: "/admin/support" },
]

// same rules the old Layout used to pick a sidebar from the URL
export function moduleKeyFromPath(pathname) {
  if (pathname.startsWith("/admin/sales")) return "sales"
  if (pathname.startsWith("/admin/finance")) return "finance"
  if (pathname.startsWith("/admin/operations") || pathname === "/admin/logs" ||
      pathname.startsWith("/admin/surveys")) return "operations"
  if (pathname.startsWith("/admin/vendor")) return "vendor"
  if (pathname.startsWith("/admin/marketing")) return "marketing"
  if (pathname.startsWith("/admin/panel-admin")) return "panel-admin"
  if (pathname.startsWith("/admin/hr")) return "hr"
  return null
}

const norm = (p) => (p.length > 1 && p.endsWith("/") ? p.slice(0, -1) : p)

export function isItemActive(item, pathname) {
  const path = norm(pathname)
  const targets = [item.to, ...(item.also || [])]
  if (item.exact) return targets.some((t) => path === t)
  return targets.some((t) => path.startsWith(t))
}

// the label of the nav item for this URL, for the top bar title
export function findActiveItem(pathname) {
  for (const mod of MODULES) {
    for (const group of mod.groups) {
      for (const item of group.items) {
        if (isItemActive(item, pathname)) return { module: mod, item }
      }
    }
  }
  const account = ACCOUNT_LINKS.find((l) => isItemActive(l, pathname))
  return account ? { module: null, item: account } : null
}
