import { Routes, Route } from "react-router-dom"
import Layout from "./components/Layout"
import Login from "./pages/Login"
import Dashboard from "./pages/Dashboard"
import Sales from "./pages/Sales"
import Marketing from "./pages/Marketing"
import Finance from "./pages/Finance"
import Operations from "./pages/Operations"
import HR from "./pages/HR"
import Campaign from "./pages/sales/Campaign"
import Leads from "./pages/sales/Leads"
import Contacts from "./pages/sales/Contacts"
import Account from "./pages/sales/Account"
import RFQ from "./pages/sales/RFQ"
import List from "./pages/sales/campaign/List"
import Templates from "./pages/sales/campaign/Templates"
import Workflow from "./pages/sales/campaign/Workflow"
import Reports from "./pages/sales/campaign/Reports"

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="sales" element={<Sales />} />
        <Route path="sales/campaign" element={<Campaign />} />
        <Route path="sales/leads" element={<Leads />} />
        <Route path="sales/contacts" element={<Contacts />} />
        <Route path="sales/account" element={<Account />} />
        <Route path="sales/rfq" element={<RFQ />} />
        <Route path="sales/campaign/list" element={<List />} />
        <Route path="sales/campaign/templates" element={<Templates />} />
        <Route path="sales/campaign/workflow" element={<Workflow />} />
        <Route path="sales/campaign/reports" element={<Reports />} />
        <Route path="marketing" element={<Marketing />} />
        <Route path="finance" element={<Finance />} />
        <Route path="operations" element={<Operations />} />
        <Route path="hr" element={<HR />} />
      </Route>
    </Routes>
  )
}

export default App
