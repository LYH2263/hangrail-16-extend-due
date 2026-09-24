import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api/client";

const icons = [
  { to: "/occupancy", icon: "━", label: "占位" },
  { to: "/orders", icon: "🏷", label: "工单" },
  { to: "/pickup", icon: "↓", label: "取件" },
  { to: "/overdue", icon: "⏰", label: "逾期" },
  { to: "/rails", icon: "═", label: "挂杆" },
  { to: "/stores", icon: "店", label: "门店" },
];

type Occ = {
  rail_id: number;
  label: string;
  length_cm: number;
  segments: { ticket_code: string; garment_name: string; start_cm: number; end_cm: number }[];
};
type Order = { id: number; ticket_code: string; garment_name: string; status: string; due_at?: string };

export default function Layout() {
  const loc = useLocation();
  const [maps, setMaps] = useState<Occ[]>([]);
  const [pickupHint, setPickupHint] = useState<Order[]>([]);
  const [overdue, setOverdue] = useState<Order[]>([]);

  useEffect(() => {
    const refresh = () => {
      api<{ id: number; label: string; length_cm: number }[]>("/rails")
        .then(async (rs) => {
          const all = await Promise.all(rs.map((r) => api<Occ>(`/occupancy/${r.id}`)));
          setMaps(all);
        })
        .catch(() => setMaps([]));

      api<Order[]>("/orders")
        .then((rows) => {
          const ready = rows
            .filter((o) => o.status === "ready" || o.status === "hanging" || o.status === "overdue")
            .slice(0, 6);
          setPickupHint(ready);
        })
        .catch(() => setPickupHint([]));

      api<Order[]>("/overdue")
        .then((rows) => setOverdue(rows.slice(0, 8)))
        .catch(() => setOverdue([]));
    };
    refresh();
    window.addEventListener("orders-changed", refresh);
    return () => window.removeEventListener("orders-changed", refresh);
  }, [loc.pathname]);

  const hangTags = maps.flatMap((m) =>
    m.segments.map((s) => ({
      ...s,
      rail: m.label,
      length_cm: m.length_cm,
      pct: ((s.end_cm - s.start_cm) / m.length_cm) * 100,
      left: (s.start_cm / m.length_cm) * 100,
      railId: m.rail_id,
    }))
  );

  return (
    <div className="hangframe-shell">
      <aside className="icon-spine" aria-label="图标轨">
        <div className="icon-spine-brand" title="HangRail">
          HR
        </div>
        {icons.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            title={n.label}
            className={({ isActive }) =>
              `spine-icon${isActive ? " spine-icon--on" : ""}`
            }
          >
            <span className="spine-icon-glyph">{n.icon}</span>
            <span className="spine-icon-tip">{n.label}</span>
          </NavLink>
        ))}
      </aside>

      <div className="hangframe-main">
        <header className="rail-ruler-chrome" aria-label="挂杆尺">
          <div className="rail-ruler-meta">
            <span className="rail-ruler-title">HangRail 挂杆尺</span>
            <span className="mono">全宽占位标尺 · 票签下垂</span>
          </div>
          <div className="rail-bar">
            <div className="rail-bar-metal" />
            <div className="rail-bar-ticks">
              {Array.from({ length: 21 }).map((_, i) => (
                <span key={i} className={i % 5 === 0 ? "tick tick--major" : "tick"} />
              ))}
            </div>
          </div>
          <div className="ticket-hang-row">
            {hangTags.length === 0 && (
              <div className="ticket-hang-empty">暂无挂票 — 打开占位图或录入工单</div>
            )}
            {hangTags.slice(0, 14).map((t, i) => (
              <div
                key={`${t.ticket_code}-${i}`}
                className="hang-tag"
                style={{ marginLeft: i === 0 ? `${Math.min(t.left, 40)}%` : undefined }}
                title={`${t.rail} ${t.start_cm}-${t.end_cm}cm`}
              >
                <div className="hang-tag-hook" />
                <div className="hang-tag-body">
                  <div className="hang-tag-code">{t.ticket_code}</div>
                  <div className="hang-tag-name">{t.garment_name}</div>
                  <div className="hang-tag-rail">{t.rail}</div>
                </div>
              </div>
            ))}
          </div>
        </header>

        <section className="hangframe-stage">
          <Outlet />
        </section>

        <footer className="bottom-tray" aria-label="取件与逾期托盘">
          <div className="tray-col">
            <div className="tray-label">
              取件托盘 <NavLink to="/pickup">打开 →</NavLink>
            </div>
            <div className="tray-chips">
              {pickupHint.length === 0 && <span className="tray-empty">无可取件</span>}
              {pickupHint.map((o) => (
                <span key={o.id} className="tray-chip">
                  {o.ticket_code}
                </span>
              ))}
            </div>
          </div>
          <div className="tray-col tray-col--warn">
            <div className="tray-label">
              逾期 <NavLink to="/overdue">查看 →</NavLink>
            </div>
            <div className="tray-chips">
              {overdue.length === 0 && <span className="tray-empty">无逾期</span>}
              {overdue.map((o) => (
                <span key={o.id} className="tray-chip tray-chip--overdue">
                  {o.ticket_code}
                </span>
              ))}
            </div>
          </div>
        </footer>
      </div>
    </div>
  );
}
