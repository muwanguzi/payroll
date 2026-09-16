"use client";

import { useToast } from "../components/Toasts";

/* A kitchen-sink page so you can eyeball every primitive in light + dark.
   Delete once you've wired your own pages. Every className here is defined
   in styles/app.css — no CSS of its own. */
export default function DemoPage() {
  const { push } = useToast();

  return (
    <>
      <div className="page-head">
        <h1>Component gallery</h1>
        <p className="sub">
          Everything below is plain markup styled by <code>app.css</code>. Toggle the theme
          from the topbar — no component re-renders, just CSS custom properties.
        </p>
      </div>

      {/* KPI row */}
      <div className="grid c4">
        <div className="stat">
          <div className="l">Active records</div>
          <div className="n">403</div>
          <div className="f">403 in total</div>
        </div>
        <div className="stat">
          <div className="l">Business units</div>
          <div className="n">15</div>
          <div className="f">consolidated view</div>
        </div>
        <div className="stat good">
          <div className="l">Passing checks</div>
          <div className="n">21</div>
        </div>
        <div className="stat bad">
          <div className="l">Data-quality flags</div>
          <div className="n">2</div>
          <div className="f">needs attention</div>
        </div>
      </div>

      {/* Two cards */}
      <div className="grid c2">
        <div className="card">
          <div className="card-head">
            <h2>Recent items</h2>
            <a className="btn sm ghost" href="#">
              View all
            </a>
          </div>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Period</th>
                  <th className="num">Amount</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Expense allowances — November</td>
                  <td>2026-11</td>
                  <td className="num">216,200,000</td>
                  <td>
                    <span className="pill warn">Reviewed</span>
                  </td>
                </tr>
                <tr>
                  <td>Payroll — month ended 27 Nov</td>
                  <td>2026-11</td>
                  <td className="num">232,450,000</td>
                  <td>
                    <span className="pill info">Calculated</span>
                  </td>
                </tr>
                <tr>
                  <td>Payroll — month ended 27 Oct</td>
                  <td>2026-10</td>
                  <td className="num">228,900,000</td>
                  <td>
                    <span className="pill good">Approved</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <h2>Detail</h2>
          </div>
          <dl className="kv">
            <dt>Reference</dt>
            <dd>NM-2026-1142</dd>
            <dt>Owner</dt>
            <dd>Hilda Rukundo</dd>
            <dt>Created</dt>
            <dd>4 Sept 2026</dd>
            <dt>State</dt>
            <dd>
              <span className="pill neutral">Draft</span>
            </dd>
          </dl>

          <div className="stepline" style={{ marginTop: 18 }}>
            <span className="step done">
              <span className="dot" /> Prepared
            </span>
            <span className="sep">›</span>
            <span className="step now">
              <span className="dot" /> Review
            </span>
            <span className="sep">›</span>
            <span className="step">
              <span className="dot" /> Approve
            </span>
            <span className="sep">›</span>
            <span className="step">
              <span className="dot" /> Disburse
            </span>
          </div>

          <div className="bar-track" style={{ marginTop: 16 }}>
            <span className="bar-fill" style={{ width: "45%" }} />
          </div>
        </div>
      </div>

      {/* Banners */}
      <div className="card">
        <div className="card-head">
          <h2>Messages</h2>
        </div>
        <div className="banner info">Heads up — this table recalculates on save.</div>
        <div className="banner warning">3 rows have a variance and cannot be approved yet.</div>
        <div className="banner error">The bank file is blocked: 2 accounts are malformed.</div>
      </div>

      {/* Form + buttons */}
      <div className="card">
        <div className="card-head">
          <h2>Form controls</h2>
        </div>
        <div className="form-grid">
          <div className="f">
            <label>Full name</label>
            <input type="text" placeholder="Jane Doe" />
          </div>
          <div className="f">
            <label>Start date</label>
            <input type="date" />
          </div>
          <div className="f">
            <label>Unit</label>
            <select>
              <option>NBS</option>
              <option>Sanyuka</option>
              <option>Next Radio</option>
            </select>
          </div>
          <div className="f">
            <label>Notes</label>
            <textarea rows={2} />
          </div>
        </div>
        <div className="form-actions">
          <button className="btn" onClick={() => push("Saved.", "success")}>
            Save
          </button>
          <button className="btn ghost" onClick={() => push("Nothing changed.")}>
            Cancel
          </button>
          <button className="btn danger" onClick={() => push("Deleted.", "error")}>
            Delete
          </button>
        </div>
      </div>
    </>
  );
}
