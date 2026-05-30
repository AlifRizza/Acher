import { useState } from "react";
import { Timeline } from "./pages/Timeline";
import { TimesheetPage } from "./pages/TimesheetPage";

type Tab = "timeline" | "timesheet";

// Two tabs for now: the screenshot Timeline and the Timesheet/export view.
// A Settings page lands once its backend (settings PUT) exists.
export default function App() {
  const [tab, setTab] = useState<Tab>("timeline");

  return (
    <div className="app">
      <nav className="tabs">
        <h1>Acher</h1>
        <button
          className={tab === "timeline" ? "tab active" : "tab"}
          onClick={() => setTab("timeline")}
        >
          Timeline
        </button>
        <button
          className={tab === "timesheet" ? "tab active" : "tab"}
          onClick={() => setTab("timesheet")}
        >
          Timesheet
        </button>
      </nav>
      {tab === "timeline" ? <Timeline /> : <TimesheetPage />}
    </div>
  );
}
