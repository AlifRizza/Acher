import { useState } from "react";
import { DayView } from "./pages/DayView";
import { TimesheetPage } from "./pages/TimesheetPage";
import { Statistics } from "./pages/Statistics";

type Tab = "day" | "timesheet" | "statistics";

// Three tabs: the ManicTime-style Day timeline, the Timesheet/export view, and
// the Statistics charts. (The earlier screenshot-grid page lives in
// pages/Timeline.tsx but is superseded by DayView and no longer routed.)
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
      </nav>
      {tab === "day" && <DayView />}
      {tab === "timesheet" && <TimesheetPage />}
      {tab === "statistics" && <Statistics />}
    </div>
  );
}
