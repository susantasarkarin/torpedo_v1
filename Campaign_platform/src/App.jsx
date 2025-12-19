import { Routes, Route, Navigate } from "react-router-dom"

import ProtectedRoute from "./components/ProtectedRoute"
import Layout from "./components/Layout"

// Auth
import Login from "./pages/Login"

// Main Pages
import Dashboard from "./pages/Dashboard"
import Sales from "./pages/Sales"
import Marketing from "./pages/Marketing"
import Finance from "./pages/Finance"
import Operations from "./pages/Operations"
import HR from "./pages/HR"

// Sales Pages
import Campaign from "./pages/sales/Campaign"
import Leads from "./pages/sales/Leads"
import Contacts from "./pages/sales/Contacts"
import ContactsImport from "./pages/sales/ContactsImport"
import Account from "./pages/sales/Account"
import RFQ from "./pages/sales/RFQ"
import List from "./pages/sales/campaign/List"
import Templates from "./pages/sales/campaign/Templates"
import Workflow from "./pages/sales/campaign/Workflow"
import Reports from "./pages/sales/campaign/Reports"

// Operations Pages
import ClientsPage from "./pages/operations/ClientsPage"
import VendorsPage from "./pages/operations/VendorsPage"
import ProjectsPage from "./pages/operations/ProjectsPage"
import ProjectDetail from "./pages/operations/ProjectDetail"
import SurveyPool from "./pages/operations/surveyPool/SurveyPool"

// Finance Pages
import FinanceCustomersPage from "./pages/finance/CustomersPage"
import FinanceCustomersImport from "./pages/finance/CustomersImport"
import FinanceVendorsPage from "./pages/finance/VendorsPage"
import FinanceItems from "./pages/finance/ItemsPage"
import EstimatesPage from "./pages/finance/EstimatesPage"
import InvoicesPage from "./pages/finance/InvoicesPage"
import BillsPage from "./pages/finance/BillsPage"
import ExpensesPage from "./pages/finance/ExpensesPage"
import PaymentsPage from "./pages/finance/PaymentsPage"
import PurchaseOrdersPage from "./pages/finance/PurchaseOrdersPage"
import ReportsPage from "./pages/finance/ReportsPage"

// User Pages
import TrafficFlowParser from "./pages/user/TrafficFlowParser"

// Settings Page
import Settings from "./pages/Settings"

// Logs Page
import LogsPage from "./pages/LogsPage"

function App() {
  return (
    <Routes>
      {/* Default: when you run app locally, go to admin login */}
      <Route path="/" element={<Navigate to="/admin/login" replace />} />

      {/* Public user page */}
      <Route path="/takesurvey" element={<TrafficFlowParser />} />

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
        <Route path="dashboard" element={<Dashboard />} />

        {/* Sales Routes */}
        <Route path="sales" element={<Sales />} />
        <Route path="sales/campaign" element={<Campaign />} />
        <Route path="sales/leads" element={<Leads />} />
        <Route path="sales/contacts" element={<Contacts />} />
        <Route path="sales/contacts/import" element={<ContactsImport />} />
        <Route path="sales/account" element={<Account />} />
        <Route path="sales/rfq" element={<RFQ />} />
        <Route path="sales/campaign/list" element={<List />} />
        <Route path="sales/campaign/templates" element={<Templates />} />
        <Route path="sales/campaign/workflow" element={<Workflow />} />
        <Route path="sales/campaign/reports" element={<Reports />} />

        {/* Marketing */}
        <Route path="marketing" element={<Marketing />} />

        {/* Finance Routes - Flat structure like Operations */}
        <Route path="finance" element={<Finance />} />
        <Route path="finance/customers" element={<FinanceCustomersPage />} />
        <Route path="finance/customers/import" element={<FinanceCustomersImport />} />
        <Route path="finance/vendors" element={<FinanceVendorsPage />} />
        <Route path="finance/invoices" element={<InvoicesPage />} />
        <Route path="finance/bills" element={<BillsPage />} />
        <Route path="finance/expenses" element={<ExpensesPage />} />
        <Route path="finance/purchase-orders" element={<PurchaseOrdersPage />} />
        <Route path="finance/payments" element={<PaymentsPage />} />
        <Route path="finance/reports" element={<ReportsPage />} />
        <Route path="finance/items" element={<FinanceItems />} />
        <Route path="finance/estimates" element={<EstimatesPage />} />
        <Route
          path="finance/settings"
          element={<div style={{ padding: "2rem" }}>Finance Settings (Coming Soon)</div>}
        />

        {/* Settings */}
        <Route path="settings" element={<Settings />} />

        {/* Logs */}
        <Route path="logs" element={<LogsPage />} />

        {/* Operations Routes */}
        <Route path="operations" element={<Operations />} />
        <Route path="operations/clients" element={<ClientsPage />} />
        <Route path="operations/vendors" element={<VendorsPage />} />
        <Route path="operations/projects" element={<ProjectsPage />} />
        <Route path="operations/projects/:projectId" element={<ProjectDetail />} />
        <Route path="operations/survey-pool" element={<SurveyPool />} />

        {/* HR */}
        <Route path="hr" element={<HR />} />
      </Route>

      {/* Catch all */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
