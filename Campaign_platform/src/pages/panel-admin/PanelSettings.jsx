import { useState } from "react"

function PanelSettings() {
  const [activeSection, setActiveSection] = useState("signup")

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Panel Settings</h2>
          <p className="card-description">Configure panel signup, email templates, and branding.</p>
        </div>

        <div className="grid grid-cols-3" style={{ marginBottom: "2rem" }}>
          <div
            className="card"
            onClick={() => setActiveSection("signup")}
            style={{
              cursor: "pointer",
              border: activeSection === "signup" ? "2px solid #3b82f6" : "1px solid #e5e7eb",
            }}
          >
            <h3 className="card-title">Signup Configuration</h3>
            <p style={{ fontSize: "0.875rem", color: "#6b7280" }}>
              Control signup form fields, validation rules, and default values.
            </p>
          </div>

          <div
            className="card"
            onClick={() => setActiveSection("email")}
            style={{
              cursor: "pointer",
              border: activeSection === "email" ? "2px solid #3b82f6" : "1px solid #e5e7eb",
            }}
          >
            <h3 className="card-title">Email Templates</h3>
            <p style={{ fontSize: "0.875rem", color: "#6b7280" }}>
              Customize welcome emails, reward notifications, and reminders.
            </p>
          </div>

          <div
            className="card"
            onClick={() => setActiveSection("branding")}
            style={{
              cursor: "pointer",
              border: activeSection === "branding" ? "2px solid #3b82f6" : "1px solid #e5e7eb",
            }}
          >
            <h3 className="card-title">Panel Branding</h3>
            <p style={{ fontSize: "0.875rem", color: "#6b7280" }}>
              Logo, colors, and panel landing page customization.
            </p>
          </div>
        </div>

        {/* Signup Configuration */}
        {activeSection === "signup" && (
          <div className="card">
            <h3 className="card-title">Signup Configuration</h3>
            <div style={{ marginTop: "1rem" }}>
              <div style={{ marginBottom: "1.5rem" }}>
                <label style={{ display: "block", fontWeight: "500", marginBottom: "0.5rem" }}>
                  Required Fields
                </label>
                <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
                  {["First Name", "Last Name", "Email", "Country", "Phone", "Date of Birth", "Gender"].map((field) => (
                    <label key={field} style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.875rem" }}>
                      <input
                        type="checkbox"
                        defaultChecked={["First Name", "Last Name", "Email", "Country"].includes(field)}
                      />
                      {field}
                    </label>
                  ))}
                </div>
              </div>

              <div style={{ marginBottom: "1.5rem" }}>
                <label style={{ display: "block", fontWeight: "500", marginBottom: "0.5rem" }}>
                  Auto-approve signups
                </label>
                <select style={{ padding: "0.5rem 1rem", borderRadius: "6px", border: "1px solid #d1d5db" }}>
                  <option value="yes">Yes - Automatically activate new panelists</option>
                  <option value="no">No - Require manual approval</option>
                </select>
              </div>

              <div style={{ marginBottom: "1.5rem" }}>
                <label style={{ display: "block", fontWeight: "500", marginBottom: "0.5rem" }}>
                  Welcome Bonus Points
                </label>
                <input
                  type="number"
                  defaultValue={50}
                  style={{ padding: "0.5rem 1rem", borderRadius: "6px", border: "1px solid #d1d5db", width: "120px" }}
                />
              </div>

              <button className="btn btn-primary">Save Signup Settings</button>
            </div>
          </div>
        )}

        {/* Email Templates */}
        {activeSection === "email" && (
          <div className="card">
            <h3 className="card-title">Email Templates</h3>
            <div style={{ marginTop: "1rem" }}>
              {[
                { name: "Welcome Email", desc: "Sent when a new panelist signs up" },
                { name: "Survey Invitation", desc: "Sent when a new survey is available" },
                { name: "Reward Notification", desc: "Sent when points are credited" },
                { name: "Password Reset", desc: "Sent when password reset is requested" },
              ].map((template) => (
                <div
                  key={template.name}
                  style={{
                    display: "flex", justifyContent: "space-between", alignItems: "center",
                    padding: "1rem", borderBottom: "1px solid #f3f4f6",
                  }}
                >
                  <div>
                    <p style={{ fontWeight: "500" }}>{template.name}</p>
                    <p style={{ fontSize: "0.75rem", color: "#6b7280" }}>{template.desc}</p>
                  </div>
                  <button className="btn btn-outline">Edit</button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Branding */}
        {activeSection === "branding" && (
          <div className="card">
            <h3 className="card-title">Panel Branding</h3>
            <div style={{ marginTop: "1rem" }}>
              <div style={{ marginBottom: "1.5rem" }}>
                <label style={{ display: "block", fontWeight: "500", marginBottom: "0.5rem" }}>
                  Panel Name
                </label>
                <input
                  type="text"
                  defaultValue="SurveyFieldwork Panel"
                  style={{ padding: "0.5rem 1rem", borderRadius: "6px", border: "1px solid #d1d5db", width: "100%", maxWidth: "400px" }}
                />
              </div>

              <div style={{ marginBottom: "1.5rem" }}>
                <label style={{ display: "block", fontWeight: "500", marginBottom: "0.5rem" }}>
                  Primary Color
                </label>
                <input type="color" defaultValue="#3b82f6" style={{ width: "60px", height: "40px", cursor: "pointer" }} />
              </div>

              <div style={{ marginBottom: "1.5rem" }}>
                <label style={{ display: "block", fontWeight: "500", marginBottom: "0.5rem" }}>
                  Panel Logo
                </label>
                <input type="file" accept="image/*" style={{ fontSize: "0.875rem" }} />
              </div>

              <button className="btn btn-primary">Save Branding</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default PanelSettings
