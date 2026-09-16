import type { PlacementProfileResponse, ValidationErrorItem } from "../types";

interface ProfilePanelProps {
  target: string;
  loading: boolean;
  profile: PlacementProfileResponse | null;
  errors: ValidationErrorItem[] | null;
}

// Derived region: populated only after a layer strip is clicked in the
// canonical SVG witness. Loading, success and failure replace only this
// block -- the original solve witness above it is never touched.
export default function ProfilePanel({ target, loading, profile, errors }: ProfilePanelProps) {
  return (
    <section className="profile-panel" data-testid="placement-profile" data-target={target}>
      <h3>层位敏感性剖面 · 目标图层 <code>{target}</code></h3>
      <p className="hint">
        假设装帧限制把该色版钉在每个指定深度（0 = 最底层），下表给出该深度下的
        <strong>最低总违背代价</strong>、相对原全局最优的<strong>增量</strong>
        及对应的 ASCII 字典序最小规范排列（复用同一份精确整数代价）。
      </p>

      {loading && <p className="profile-status" data-testid="profile-loading">剖面计算中…</p>}

      {!loading && errors && (
        <div className="profile-error" data-testid="profile-error" role="alert">
          <strong>剖面加载失败</strong>（原求解见证保持不变）：
          <ul>
            {errors.map((e, i) => (
              <li key={i}>
                <code>{e.pointer || "/"}</code>
                <span>{e.message}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!loading && profile && (
        <>
          <p className="profile-summary" data-testid="profile-summary">
            原全局最优总代价 <strong>{profile.optimal_cost.toLocaleString()}</strong>
            ；共 {profile.depths.length} 个深度（与图层数相同），
            其中 {profile.depths.filter((d) => d.delta === 0).length} 个深度可保持最优。
          </p>
          <div className="obs-table-wrap">
            <table className="obs-table profile-table">
              <thead>
                <tr>
                  <th>指定深度</th>
                  <th className="num">最低总代价</th>
                  <th className="num">相对最优增量</th>
                  <th>规范排列（底 → 顶，目标钉在该深度）</th>
                </tr>
              </thead>
              <tbody>
                {profile.depths.map((row) => (
                  <tr
                    key={row.depth}
                    data-testid="profile-depth-row"
                    data-depth={row.depth}
                    className={row.delta === 0 ? "profile-optimal" : "profile-penalized"}
                  >
                    <td className="strong">#{row.depth}</td>
                    <td className="num">{row.cost.toLocaleString()}</td>
                    <td className="num">
                      <span className={`badge ${row.delta === 0 ? "ok" : "bad"}`}>
                        {row.delta === 0 ? "±0" : `+${row.delta.toLocaleString()}`}
                      </span>
                    </td>
                    <td>
                      <span className="order-line">
                        {row.order.map((id, i) => (
                          <span
                            key={`${id}-${i}`}
                            className={
                              i === row.depth ? "order-chip profile-target" : "order-chip"
                            }
                            data-is-target={i === row.depth ? "1" : "0"}
                          >
                            {id}
                            {i < row.order.length - 1 && <em> ▲ </em>}
                          </span>
                        ))}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
