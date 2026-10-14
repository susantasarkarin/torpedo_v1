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
    <PageShell title="Members" description="Every SurveyFieldwork Panel member — profile, tier, survey log, points and flags. Click a member for the detail panel.">
      <PanelistManagement mode="members" />
    </PageShell>
  )
}

const RECRUITMENT_TABS = [
  { key: "leads", label: "Leads & invites" },
  { key: "suppliers", label: "Traffic suppliers" },
  { key: "traffic", label: "Landing traffic" },
  { key: "email", label: "Invitation email" },
]

export function RecruitmentSection() {
  const [tab, setTab] = useTab(RECRUITMENT_TABS)
  return (
    <PageShell title="Recruitment" description="Where new members come from: lead lists and invitations, paid and partner traffic suppliers, and landing-page visits.">
      <Tabs tabs={RECRUITMENT_TABS} active={tab} onChange={setTab} />
      {tab === "leads" && <PanelistManagement mode="recruitment" />}
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
    <PageShell title="Rewards" description="Live from the SurveyFieldwork Panel: points earned and on hold, gift cards to send, and points by reason. 100 points = ₹10 / £1 / $1.">
      <RewardsPoints embedded />
    </PageShell>
  )
}
