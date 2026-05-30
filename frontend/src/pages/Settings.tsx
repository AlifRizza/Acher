import { useEffect, useState } from "react";
import type { AppConfig } from "../types";
import { getConfig, saveConfig } from "../lib/api";

// Editable runtime settings. Loads the current config, lets the user change it,
// and saves via PUT /api/config. The daemon reads config at startup, so changes
// take effect after a restart — the form says so explicitly.

const RETENTION_OPTIONS = ["1_week", "1_month", "3_months", "6_months", "never"];
const BROWSER_OPTIONS = ["Chrome", "Arc", "Brave", "Safari", "Firefox"];

export function Settings() {
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getConfig()
      .then(setCfg)
      .catch((e) => setLoadErr(String(e)));
  }, []);

  // Generic field updater; clears any prior save status as soon as you edit.
  function set<K extends keyof AppConfig>(key: K, value: AppConfig[K]) {
    setCfg((c) => (c ? { ...c, [key]: value } : c));
    setSaved(false);
    setSaveErr(null);
  }

  function toggleBrowser(name: string, on: boolean) {
    if (!cfg) return;
    const next = on
      ? [...cfg.browsers, name]
      : cfg.browsers.filter((b) => b !== name);
    set("browsers", next);
  }

  async function onSave() {
    if (!cfg) return;
    setSaving(true);
    setSaveErr(null);
    setSaved(false);
    try {
      const updated = await saveConfig(cfg);
      setCfg(updated);
      setSaved(true);
    } catch (e) {
      setSaveErr(String(e instanceof Error ? e.message : e));
    } finally {
      setSaving(false);
    }
  }

  if (loadErr) return <div className="error">Failed to load settings: {loadErr}</div>;
  if (!cfg) return <div className="empty">Loading settings…</div>;

  return (
    <div className="settings">
      <div className="settings-note">
        Changes are saved to <code>config.json</code> and take effect the next
        time the Acher daemon restarts (e.g. <code>acher uninstall &amp;&amp; acher
        install</code>, or your next login).
      </div>

      <div className="settings-grid">
        <label className="setting">
          <span>Screenshot interval (minutes)</span>
          <input
            type="number"
            min={1}
            max={120}
            value={cfg.interval_minutes}
            onChange={(e) => set("interval_minutes", Number(e.target.value))}
          />
          <small>Any whole number from 1 to 120.</small>
        </label>

        <label className="setting">
          <span>Idle threshold (minutes)</span>
          <input
            type="number"
            min={1}
            max={120}
            value={cfg.idle_threshold_minutes}
            onChange={(e) => set("idle_threshold_minutes", Number(e.target.value))}
          />
          <small>No input for this long pauses capture (1–120).</small>
        </label>

        <label className="setting">
          <span>Activity sample interval (seconds)</span>
          <input
            type="number"
            min={1}
            max={60}
            value={cfg.activity_sample_seconds}
            onChange={(e) => set("activity_sample_seconds", Number(e.target.value))}
          />
          <small>How often presence/app is sampled (1–60).</small>
        </label>

        <label className="setting">
          <span>Retention</span>
          <select
            value={cfg.retention_period}
            onChange={(e) => set("retention_period", e.target.value)}
          >
            {RETENTION_OPTIONS.map((o) => (
              <option key={o} value={o}>
                {o.replace("_", " ")}
              </option>
            ))}
          </select>
          <small>Screenshots older than this are deleted ("never" keeps all).</small>
        </label>

        <label className="setting">
          <span>Manual-capture hotkey</span>
          <input
            type="text"
            value={cfg.hotkey}
            onChange={(e) => set("hotkey", e.target.value)}
          />
          <small>e.g. <code>ctrl+alt+shift+s</code> (cmd/option also accepted).</small>
        </label>

        <div className="setting">
          <span>Browsers to read tab titles from</span>
          <div className="checks">
            {BROWSER_OPTIONS.map((b) => (
              <label key={b} className="check">
                <input
                  type="checkbox"
                  checked={cfg.browsers.includes(b)}
                  onChange={(e) => toggleBrowser(b, e.target.checked)}
                />
                {b}
              </label>
            ))}
          </div>
        </div>
      </div>

      <div className="settings-actions">
        <button className="btn" onClick={onSave} disabled={saving}>
          {saving ? "Saving…" : "Save settings"}
        </button>
        {saved && <span className="save-ok">✓ Saved — restart the daemon to apply.</span>}
        {saveErr && <span className="error inline">{saveErr}</span>}
      </div>
    </div>
  );
}
