import type { ObservationResult } from "../types";

interface ObservationTableProps {
  rows: ObservationResult[];
  totalCost: number;
  title?: string;
}

export default function ObservationTable({ rows, totalCost, title }: ObservationTableProps) {
  const paid = rows.filter((r) => r.violated).length;
  const recomputed = rows.reduce((sum, r) => sum + r.cost, 0);

  return (
    <section className="obs-table-wrap">
      {title && <h4>{title}</h4>}
      <table className="obs-table">
        <thead>
          <tr>
            <th>#</th>
            <th>下层 lower</th>
            <th>上层 upper</th>
            <th>权重</th>
            <th>下层位置</th>
            <th>上层位置</th>
            <th>判定</th>
            <th className="num">计入代价</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={r.violated ? "violated" : "satisfied"}>
              <td className="muted">{i + 1}</td>
              <td>{r.lower}</td>
              <td>{r.upper}</td>
              <td className="num">{r.weight.toLocaleString()}</td>
              <td className="num">{r.lower_position}</td>
              <td className="num">{r.upper_position}</td>
              <td>
                <span className={`badge ${r.violated ? "bad" : "ok"}`}>
                  {r.violated ? "违背" : "满足"}
                </span>
              </td>
              <td className="num">{r.cost.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={7}>
              逐项求和复算（{paid}/{rows.length} 条违背）
            </td>
            <td className="num strong">{recomputed.toLocaleString()}</td>
          </tr>
        </tfoot>
      </table>
      <p className={`recheck ${recomputed === totalCost ? "ok" : "mismatch"}`}>
        {recomputed === totalCost
          ? `✓ 明细求和 ${recomputed.toLocaleString()} 与服务端总代价 ${totalCost.toLocaleString()} 一致`
          : `✗ 明细求和 ${recomputed.toLocaleString()} 与总代价 ${totalCost.toLocaleString()} 不一致`}
      </p>
    </section>
  );
}
