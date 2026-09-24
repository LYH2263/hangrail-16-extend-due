import { useEffect, useState } from "react";
import { api } from "../api/client";
type O = { id: number; ticket_code: string; garment_name: string; length_cm: number; status: string; due_at: string; hung_at: string | null };

function toLocalInputValue(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function OrdersPage() {
  const [rows, setRows] = useState<O[]>([]);
  const [msg, setMsg] = useState(""); const [err, setErr] = useState("");
  const [extId, setExtId] = useState<number | null>(null);
  const [newDue, setNewDue] = useState("");
  const reload = () => api<O[]>("/orders").then(setRows);
  useEffect(() => { reload(); }, []);
  async function hang(id: number) {
    setMsg(""); setErr("");
    try {
      const o = await api<O>("/hang", { method: "POST", body: JSON.stringify({ order_id: id }) });
      setMsg(`${o.ticket_code} 已上杆`);
      reload();
      window.dispatchEvent(new Event("orders-changed"));
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }
  function startExtend(o: O) {
    setMsg(""); setErr("");
    setExtId(o.id);
    setNewDue(toLocalInputValue(o.due_at));
  }
  async function confirmExtend(id: number) {
    setMsg(""); setErr("");
    try {
      const o = await api<O>(`/orders/${id}/extend`, { method: "POST", body: JSON.stringify({ due_at: newDue }) });
      setMsg(`${o.ticket_code} 到期已延至 ${new Date(o.due_at).toLocaleString()}`);
      setExtId(null);
      reload();
      window.dispatchEvent(new Event("orders-changed"));
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }
  return (<>
    <h2>工单</h2>
    {msg && <div className="ok">{msg}</div>}
    {err && <div className="err">{err}</div>}
    <table className="table"><thead><tr><th>票号</th><th>衣物</th><th>衣长</th><th>状态</th><th>到期</th><th></th></tr></thead>
    <tbody>{rows.map(o => <tr key={o.id}><td className="mono">{o.ticket_code}</td><td>{o.garment_name}</td><td className="mono">{o.length_cm}cm</td><td>{o.status}</td>
      <td className="mono">{new Date(o.due_at).toLocaleString()}</td>
      <td>
        {(o.status === "ready" || o.status === "overdue") && <button onClick={() => hang(o.id)}>上杆</button>}
        {(o.status === "hung" || o.status === "overdue") && (extId === o.id
          ? <span className="ext-inline"><input type="datetime-local" value={newDue} onChange={e => setNewDue(e.target.value)} />
            <button onClick={() => confirmExtend(o.id)}>确认延期</button>
            <button onClick={() => setExtId(null)}>取消</button></span>
          : <button onClick={() => startExtend(o)}>延期</button>)}
      </td>
    </tr>)}</tbody></table>
  </>);
}
