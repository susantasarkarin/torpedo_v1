import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import ProtectedRoute from "./components/ProtectedRoute";

import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Sales from "./pages/Sales";
import Marketing from "./pages/Marketing";
import Finance from "./pages/Finance";
import Operations from "./pages/Operations";
import HR from "./pages/HR";

import Campaign from "./pages/sales/Campaign";
import Leads from "./pages/sales/Leads";
import Contacts from "./pages/sales/Contacts";
import Account from "./pages/sales/Account";
import RFQ from "./pages/sales/RFQ";
import List from "./pages/sales/campaign/List";
import Templates from "./pages/sales/campaign/Templates";
import Workflow from "./pages/sales/campaign/Workflow";
import Reports from "./pages/sales/campaign/Reports";

import ClientsPage from "./pages/operations/ClientsPage";
import VendorsPage from "./pages/operations/VendorsPage";

function App() {
  return (
    <Routes>
      {/* Redirect root `/` to login */}
      <Route path="/" element={<Navigate to="/login" replace />} />

      {/* Public login page */}
      <Route path="/login" element={<Login />} />

      {/* Protected pages inside Layout */}
      <Route path="/" element={<Layout />}>
        <Route
          path="dashboard"
          element={
            <ProtectedRoute>
              <Dashboard />
            </ProtectedRoute>
          }
        />
        <Route path="sales" element={<ProtectedRoute><Sales /></ProtectedRoute>} />
        <Route path="sales/campaign" element={<ProtectedRoute><Campaign /></ProtectedRoute>} />
        <Route path="sales/leads" element={<ProtectedRoute><Leads /></ProtectedRoute>} />
        <Route path="sales/contacts" element={<ProtectedRoute><Contacts /></ProtectedRoute>} />
        <Route path="sales/account" element={<ProtectedRoute><Account /></ProtectedRoute>} />
        <Route path="sales/rfq" element={<ProtectedRoute><RFQ /></ProtectedRoute>} />
        <Route path="sales/campaign/list" element={<ProtectedRoute><List /></ProtectedRoute>} />
        <Route path="sales/campaign/templates" element={<ProtectedRoute><Templates /></ProtectedRoute>} />
        <Route path="sales/campaign/workflow" element={<ProtectedRoute><Workflow /></ProtectedRoute>} />
        <Route path="sales/campaign/reports" element={<ProtectedRoute><Reports /></ProtectedRoute>} />
        <Route path="marketing" element={<ProtectedRoute><Marketing /></ProtectedRoute>} />
        <Route path="finance" element={<ProtectedRoute><Finance /></ProtectedRoute>} />
        <Route path="operations" element={<ProtectedRoute><Operations /></ProtectedRoute>} />
        <Route path="hr" element={<ProtectedRoute><HR /></ProtectedRoute>} />

         {/* Operations Module */}
        <Route path="operations" element={<ProtectedRoute><Operations /></ProtectedRoute>} />
        <Route path="operations/clients" element={<ProtectedRoute><ClientsPage /></ProtectedRoute>} />
        <Route path="operations/vendors" element={<ProtectedRoute><VendorsPage /></ProtectedRoute>} />
        {/* Later you can add vendors, projects, reports, etc. */}
      </Route>
    </Routes>
  );
}

export default App;
