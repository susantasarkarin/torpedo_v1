import { Suspense, lazy } from "react"
import { Routes, Route, Navigate } from "react-router-dom"

import ProtectedRoute from "./components/ProtectedRoute"
import Layout from "./components/Layout"
import { PageLoading } from "./components/ui/PageLayout"

// Auth - Keep non-lazy for fast initial load
import Login from "./pages/Login"

// Public user pages - Keep non-lazy
import TrafficFlowParser from "./pages/user/TrafficFlowParser"
import SurveyError from "./pages/user/SurveyError"

// ============== LAZY LOADED PAGES ==============
// Main Pages
const Dashboard = lazy(() => import("./pages/Dashboard"))
const Marketing = lazy(() => import("./pages/Marketing"))
const Finance = lazy(() => import("./pages/Finance"))
const Operations = lazy(() => import("./pages/Operations"))
const HR = lazy(() => import("./pages/HR"))

// Sales Pages
const Campaign = lazy(() => import("./pages/sales/Campaign"))
const Leads = lazy(() => import("./pages/sales/Leads"))
const LeadsImport = lazy(() => import("./pages/sales/LeadsImport"))
const LeadDetail = lazy(() => import("./pages/sales/LeadDetail"))
const Contacts = lazy(() => import("./pages/sales/Contacts"))
const ContactsImport = lazy(() => import("./pages/sales/ContactsImport"))
const Account = lazy(() => import("./pages/sales/Account"))
const CompanyDetail = lazy(() => import("./pages/sales/CompanyDetail"))
const RFQ = lazy(() => import("./pages/sales/RFQ"))
const List = lazy(() => import("./pages/sales/campaign/List"))
const Templates = lazy(() => import("./pages/sales/campaign/Templates"))
const Workflow = lazy(() => import("./pages/sales/campaign/Workflow"))
const Reports = lazy(() => import("./pages/sales/campaign/Reports"))
const AILeads = lazy(() => import("./pages/sales/campaign/AILeads"))
const AILeadDetail = lazy(() => import("./pages/sales/campaign/AILeadDetail"))
const SalesDashboard = lazy(() => import("./pages/sales/SalesDashboard"))

// Operations Pages
const ClientsPage = lazy(() => import("./pages/operations/ClientsPage"))
const VendorsPage = lazy(() => import("./pages/operations/VendorsPage"))
const ProjectsPage = lazy(() => import("./pages/operations/ProjectsPage"))
const ProjectDetail = lazy(() => import("./pages/operations/ProjectDetail"))
const SurveyPool = lazy(() => import("./pages/operations/surveyPool/SurveyPool"))
const TrafficManagement = lazy(() => import("./pages/operations/TrafficManagement"))
const CPXCallbackLogs = lazy(() => import("./pages/operations/CPXCallbackLogs"))
const AccountsPage = lazy(() => import("./pages/operations/AccountsPage"))

// Finance Pages
const FinanceCustomersPage = lazy(() => import("./pages/finance/CustomersPage"))
const FinanceCustomersImport = lazy(() => import("./pages/finance/CustomersImport"))
const FinanceVendorsPage = lazy(() => import("./pages/finance/VendorsPage"))
const FinanceItems = lazy(() => import("./pages/finance/ItemsPage"))
const EstimatesPage = lazy(() => import("./pages/finance/EstimatesPage"))
const EstimatesImport = lazy(() => import("./pages/finance/EstimatesImport"))
const InvoicesPage = lazy(() => import("./pages/finance/InvoicesPage"))
const InvoicesImport = lazy(() => import("./pages/finance/InvoicesImport"))
const BillsPage = lazy(() => import("./pages/finance/BillsPage"))
const BillsImport = lazy(() => import("./pages/finance/BillsImport"))
const ExpensesPage = lazy(() => import("./pages/finance/ExpensesPage"))
const PaymentsPage = lazy(() => import("./pages/finance/PaymentsPage"))
const PaymentsImport = lazy(() => import("./pages/finance/PaymentsImport"))
const PurchaseOrdersPage = lazy(() => import("./pages/finance/PurchaseOrdersPage"))
const PurchaseOrdersImport = lazy(() => import("./pages/finance/PurchaseOrdersImport"))
const ReportsPage = lazy(() => import("./pages/finance/ReportsPage"))

// Vendor Pages
const VendorDashboard = lazy(() => import("./pages/vendor/VendorDashboard"))
const UnifiedVendorsPage = lazy(() => import("./pages/vendor/UnifiedVendorsPage"))

// Profile Page
const MyProfile = lazy(() => import("./pages/MyProfile"))

// Mail Pool
const MailPool = lazy(() => import("./pages/MailPool"))

// Settings Page
const Settings = lazy(() => import("./pages/Settings"))

// AI Database Page
const AIDatabase = lazy(() => import("./pages/AIDatabase"))

// Logs Page
const LogsPage = lazy(() => import("./pages/LogsPage"))

// Projects Page
const Projects = lazy(() => import("./pages/Projects"))

// Support Page
const Support = lazy(() => import("./pages/Support"))

// Wrapper for lazy loaded pages with consistent loading state
const LazyPage = ({ children }) => (
  <Suspense fallback={<PageLoading />}>
    {children}
  </Suspense>
)

function App() {
  return (
    <Routes>
      {/* Default: when you run app locally, go to admin login */}
      <Route path="/" element={<Navigate to="/admin/login" replace />} />

      {/* Public user pages */}
      <Route path="/takesurvey" element={<TrafficFlowParser />} />
      <Route path="/survey-error" element={<SurveyError />} />

      {/* Admin login page */}
      <Route path="/admin/login" element={<Login />} />

      {/* Admin protected routes */}
      <Route
        path="/admin"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        {/* Dashboard */}
        <Route path="dashboard" element={<LazyPage><Dashboard /></LazyPage>} />

        {/* Sales Routes */}
        <Route path="sales" element={<LazyPage><SalesDashboard /></LazyPage>} />
        <Route path="sales/campaign" element={<LazyPage><Campaign /></LazyPage>} />
        <Route path="sales/leads" element={<LazyPage><Leads /></LazyPage>} />
        <Route path="sales/leads/import" element={<LazyPage><LeadsImport /></LazyPage>} />
        <Route path="sales/leads/:leadId" element={<LazyPage><LeadDetail /></LazyPage>} />
        <Route path="sales/contacts" element={<LazyPage><Contacts /></LazyPage>} />
        <Route path="sales/contacts/import" element={<LazyPage><ContactsImport /></LazyPage>} />
        <Route path="sales/account" element={<LazyPage><Account /></LazyPage>} />
        <Route path="sales/account/:companyName" element={<LazyPage><CompanyDetail /></LazyPage>} />
        <Route path="sales/rfq" element={<LazyPage><RFQ /></LazyPage>} />
        <Route path="sales/campaign/list" element={<LazyPage><List /></LazyPage>} />
        <Route path="sales/campaign/ai-leads" element={<LazyPage><AIDatabase /></LazyPage>} />
        <Route path="sales/campaign/ai-leads/manage" element={<LazyPage><AILeads /></LazyPage>} />
        <Route path="sales/campaign/ai-leads/:leadId" element={<LazyPage><AILeadDetail /></LazyPage>} />
        <Route path="sales/campaign/templates" element={<LazyPage><Templates /></LazyPage>} />
        <Route path="sales/campaign/workflow" element={<LazyPage><Workflow /></LazyPage>} />
        <Route path="sales/campaign/reports" element={<LazyPage><Reports /></LazyPage>} />

        {/* Marketing */}
        <Route path="marketing" element={<LazyPage><Marketing /></LazyPage>} />

        {/* Finance Routes - Flat structure like Operations */}
        <Route path="finance" element={<LazyPage><Finance /></LazyPage>} />
        <Route path="finance/customers" element={<LazyPage><FinanceCustomersPage /></LazyPage>} />
        <Route path="finance/customers/import" element={<LazyPage><FinanceCustomersImport /></LazyPage>} />
        <Route path="finance/vendors" element={<LazyPage><FinanceVendorsPage /></LazyPage>} />
        <Route path="finance/invoices" element={<LazyPage><InvoicesPage /></LazyPage>} />
        <Route path="finance/invoices/import" element={<LazyPage><InvoicesImport /></LazyPage>} />
        <Route path="finance/bills" element={<LazyPage><BillsPage /></LazyPage>} />
        <Route path="finance/bills/import" element={<LazyPage><BillsImport /></LazyPage>} />
        <Route path="finance/expenses" element={<LazyPage><ExpensesPage /></LazyPage>} />
        <Route path="finance/purchase-orders" element={<LazyPage><PurchaseOrdersPage /></LazyPage>} />
        <Route path="finance/purchase-orders/import" element={<LazyPage><PurchaseOrdersImport /></LazyPage>} />
        <Route path="finance/payments" element={<LazyPage><PaymentsPage /></LazyPage>} />
        <Route path="finance/payments/import" element={<LazyPage><PaymentsImport /></LazyPage>} />
        <Route path="finance/reports" element={<LazyPage><ReportsPage /></LazyPage>} />
        <Route path="finance/items" element={<LazyPage><FinanceItems /></LazyPage>} />
        <Route path="finance/estimates" element={<LazyPage><EstimatesPage /></LazyPage>} />
        <Route path="finance/estimates/import" element={<LazyPage><EstimatesImport /></LazyPage>} />
        <Route
          path="finance/settings"
          element={<div style={{ padding: "2rem" }}>Finance Settings (Coming Soon)</div>}
        />

        {/* Settings */}
        <Route path="settings" element={<LazyPage><Settings /></LazyPage>} />

        {/* Profile */}
        <Route path="profile" element={<LazyPage><MyProfile /></LazyPage>} />

        {/* Mail Pool - Consolidated Email Activity */}
        <Route path="mail-pool" element={<LazyPage><MailPool /></LazyPage>} />

        {/* Logs */}
        <Route path="logs" element={<LazyPage><LogsPage /></LazyPage>} />

        {/* Operations Routes */}
        <Route path="operations" element={<LazyPage><Operations /></LazyPage>} />
        <Route path="operations/accounts" element={<LazyPage><AccountsPage /></LazyPage>} />
        <Route path="operations/clients" element={<LazyPage><ClientsPage /></LazyPage>} />
        <Route path="operations/vendors" element={<LazyPage><VendorsPage /></LazyPage>} />
        <Route path="operations/projects" element={<LazyPage><ProjectsPage /></LazyPage>} />
        <Route path="operations/projects/:projectId" element={<LazyPage><ProjectDetail /></LazyPage>} />
        <Route path="operations/survey-pool" element={<LazyPage><SurveyPool /></LazyPage>} />
        <Route path="operations/traffic" element={<LazyPage><TrafficManagement /></LazyPage>} />
        <Route path="operations/reports" element={<LazyPage><CPXCallbackLogs /></LazyPage>} />

        {/* Vendor Routes */}
        <Route path="vendor" element={<LazyPage><VendorDashboard /></LazyPage>} />
        <Route path="vendor/all" element={<LazyPage><UnifiedVendorsPage /></LazyPage>} />
        <Route path="vendor/panel" element={<LazyPage><UnifiedVendorsPage /></LazyPage>} />
        <Route path="vendor/billing" element={<LazyPage><UnifiedVendorsPage /></LazyPage>} />
        <Route path="vendor/payments" element={<div style={{ padding: "2rem" }}>Vendor Payments (Coming Soon)</div>} />
        <Route path="vendor/reports" element={<div style={{ padding: "2rem" }}>Vendor Reports (Coming Soon)</div>} />

        {/* HR */}
        <Route path="hr" element={<LazyPage><HR /></LazyPage>} />

        {/* Projects - Project Management */}
        <Route path="projects" element={<LazyPage><Projects /></LazyPage>} />

        {/* Support - Ticket Management */}
        <Route path="support" element={<LazyPage><Support /></LazyPage>} />
      </Route>

      {/* Catch all */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
