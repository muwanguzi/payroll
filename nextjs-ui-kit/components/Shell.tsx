"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { IconSprite } from "./IconSprite";
import { applyTheme, isDark, nextTheme, type Theme } from "../lib/theme";

/* ---------------------------------------------------------------------------
   Edit this to your app's routes. `match` (optional) marks the link active for
   a path prefix as well as an exact hit — mirror of the Django template's
   `request.path|slice` checks.
--------------------------------------------------------------------------- */
type NavItem = { href: string; label: string; icon: string; match?: string };
const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: "Overview",
    items: [
      { href: "/", label: "Dashboard", icon: "i-dashboard" },
      { href: "/reports", label: "Reports", icon: "i-chart", match: "/reports" },
      { href: "/documents", label: "Documents", icon: "i-doc", match: "/documents" },
    ],
  },
  {
    group: "Operate",
    items: [
      { href: "/records", label: "Records", icon: "i-receipt", match: "/records" },
      { href: "/people", label: "People", icon: "i-users", match: "/people" },
    ],
  },
  {
    group: "Configure",
    items: [{ href: "/settings", label: "Settings", icon: "i-settings", match: "/settings" }],
  },
];

export type ShellUser = { name: string; role?: string } | null;

export function Shell({
  children,
  crumb,
  user = null,
  onSignOut,
}: {
  children: React.ReactNode;
  /** breadcrumb node for the topbar, e.g. <><a href="/">Home</a> / <b>Detail</b></> */
  crumb?: React.ReactNode;
  user?: ShellUser;
  onSignOut?: () => void;
}) {
  const path = usePathname() || "/";
  const [navOpen, setNavOpen] = useState(false);
  const [dark, setDark] = useState(false);

  useEffect(() => setDark(isDark()), []);
  useEffect(() => setNavOpen(false), [path]);

  const toggleTheme = () => {
    const cur = (document.documentElement.getAttribute("data-theme") || "") as Theme;
    const next = nextTheme(cur);
    applyTheme(next);
    setDark(next === "dark");
  };

  const active = (it: NavItem) =>
    path === it.href || (it.match ? path.startsWith(it.match) : false);

  return (
    <>
      <IconSprite />
      <div className={`app${navOpen ? " nav-open" : ""}`}>
        <div className="scrim" onClick={() => setNavOpen(false)} />

        <aside className="sidebar">
          <div className="brand">
            {/* swap for your logo in /public */}
            <img className="brand-logo" src="/next-media-logo.png" alt="Logo" />
            <span className="divider" />
            <span className="tag">
              Your
              <br />
              App
            </span>
          </div>

          <nav>
            {NAV.map((g) => (
              <div className="nav-group" key={g.group}>
                <div className="label">{g.group}</div>
                {g.items.map((it) => (
                  <Link
                    key={it.href}
                    href={it.href}
                    className={`nav-link${active(it) ? " active" : ""}`}
                  >
                    <svg className="ico">
                      <use href={`#${it.icon}`} />
                    </svg>{" "}
                    {it.label}
                  </Link>
                ))}
              </div>
            ))}
          </nav>

          <div className="spacer" />
          {user && (
            <div className="side-foot">
              Signed in as <b style={{ color: "var(--ink-soft)" }}>{user.name}</b>
              <br />
              {user.role || "No role"}
            </div>
          )}
        </aside>

        <div className="main">
          <header className="topbar">
            <button
              className="icon-btn menu-btn"
              onClick={() => setNavOpen((v) => !v)}
              aria-label="Menu"
            >
              <svg width="18" height="18">
                <use href="#i-menu" />
              </svg>
            </button>

            <div className="crumb">{crumb}</div>
            <div className="push" />

            <button
              className="icon-btn"
              onClick={toggleTheme}
              title="Toggle theme"
              aria-label="Toggle theme"
            >
              <svg width="17" height="17">
                <use href={dark ? "#i-moon" : "#i-sun"} />
              </svg>
            </button>

            {user && (
              <>
                <div className="who-chip">
                  <span className="av">{user.name.slice(0, 2).toUpperCase()}</span>
                  <span>
                    <span className="nm">{user.name}</span>
                    <br />
                    <span className="rl">{user.role || "—"}</span>
                  </span>
                </div>
                {onSignOut && (
                  <button
                    className="icon-btn"
                    onClick={onSignOut}
                    title="Sign out"
                    aria-label="Sign out"
                  >
                    <svg width="16" height="16">
                      <use href="#i-external" />
                    </svg>
                  </button>
                )}
              </>
            )}
          </header>

          <main className="content">{children}</main>
        </div>
      </div>
    </>
  );
}
