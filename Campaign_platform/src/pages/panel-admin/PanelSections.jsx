import { PageShell, Tabs } from "../../components/panel-admin/ui"
import { useTab } from "../../components/panel-admin/tokens"
import PanelistManagement from "./PanelistManagement"
import TrafficSuppliers from "./TrafficSuppliers"
import TrafficFunnel from "./TrafficFunnel"
import PanelDashboard from "./PanelDashboard"
import ProfilingAdmin from "./ProfilingAdmin"
import RewardsPoints from "./RewardsPoints"

/**
 * The Panel module's sections (Overview lives in PanelOverview.jsx). Each one
 * is a page shell around the existing screens, so every section has the same
 * header and tab layout.
 */

export function MembersSection() {
  return (
    <PageShell>
      <PanelistManagement mode="members" />
    </PageShell>
  )
}

const RECRUITMENT_TABS = [
  { key: "leads", label: "Leads" },
  { key: "approved", label: "Approved panelists" },
  { key: "suppliers", label: "Traffic suppliers" },
  { key: "traffic", label: "Landing traffic" },
  { key: "email", label: "Invitation email" },
]

export function RecruitmentSection() {
  const [tab, setTab] = useTab(RECRUITMENT_TABS)
  return (
    <PageShell title="Recruitment" description="Lead lists, invitations, traffic suppliers and landing-page visits.">
      <Tabs tabs={RECRUITMENT_TABS} active={tab} onChange={setTab} />
      {/* One instance for both lists, so switching Leads ↔ Approved keeps it
          mounted (no repeat country/status fetches, filters carry over). */}
      {(tab === "leads" || tab === "approved") && (
        <PanelistManagement mode="recruitment" view={tab === "approved" ? "panelist-approved" : "panelist-leads"} />
      )}
      {tab === "suppliers" && <TrafficSuppliers embedded />}
      {tab === "traffic" && <TrafficFunnel embedded />}
      {tab === "email" && <PanelDashboard section="email" />}
    </PageShell>
  )
}

export function QualitySection() {
  return (
    <PageShell title="Profiling & Quality" description="Profile completion by section and tier, answer quality (speeders, straight-liners, drop-offs), flags and Tier 2 review, and the brand lists the questions use.">
      <ProfilingAdmin embedded />
    </PageShell>
  )
}

export function RewardsSection() {
  return (
    <PageShell>
      <RewardsPoints embedded />
    </PageShell>
  )
}
