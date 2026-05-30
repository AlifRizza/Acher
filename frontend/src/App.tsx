import { useState } from "react";
import { DayView } from "./pages/DayView";
import { TimesheetPage } from "./pages/TimesheetPage";
import { Statistics } from "./pages/Statistics";
import { Settings } from "./pages/Settings";

type Tab = "day" | "timesheet" | "statistics" | "settings";

// Four tabs: the ManicTime-style Day timeline (with the screenshot grid below
// it), the Timesheet/export view, the Statistics charts, and Settings. (The
// earlier standalone grid page in pages/Timeline.tsx is superseded by DayView.)
export default function App() {
  const [tab, setTab] = useState<Tab>("day");

  return (
    <div className="app">
      <nav className="tabs">
        <h1>Acher</h1>
        <button className={tab === "day" ? "tab active" : "tab"} onClick={() => setTab("day")}>
          Day
        </button>
        <button
          className={tab === "timesheet" ? "tab active" : "tab"}
          onClick={() => setTab("timesheet")}
        >
          Timesheet
        </button>
        <button
          className={tab === "statistics" ? "tab active" : "tab"}
          onClick={() => setTab("statistics")}
        >
          Statistics
        </button>
        <button
          className={tab === "settings" ? "tab active" : "tab"}
          onClick={() => setTab("settings")}
        >
          Settings
        </button>
      </nav>
      {tab === "day" && <DayView />}
      {tab === "timesheet" && <TimesheetPage />}
      {tab === "statistics" && <Statistics />}
      {tab === "settings" && <Settings />}
    </div>
  );
}
