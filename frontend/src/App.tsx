import { useMemo, useRef, useState } from "react";
import { fetchPlacementProfile, solveProblem, SolveError } from "./api";
import type {
  ObservationInput,
  PlacementProfileResponse,
  ProblemPayload,
  SolutionResponse,
  ValidationErrorItem,
} from "./types";
import StackTrack from "./components/StackTrack";
import ObservationTable from "./components/ObservationTable";
import ProfilePanel from "./components/ProfilePanel";

interface ObservationDraft {
  lower: string;
  upper: string;
  weight: string; // keep as text so invalid input is visible before submit
}

const ID_RE = /^[A-Za-z0-9_-]{1,24}$/;

const SAMPLE: { layers: string[]; observations: ObservationDraft[] } = {
  layers: ["A", "B", "C", "D"],
  observations: [
    { lower: "A", upper: "B", weight: "8" },
    { lower: "A", upper: "C", weight: "1" },
    { lower: "A", upper: "D", weight: "3" },
    { lower: "B", upper: "A", weight: "1" },
    { lower: "B", upper: "C", weight: "7" },
    { lower: "C", upper: "A", weight: "1" },
    { lower: "C", upper: "D", weight: "8" },
    { lower: "D", upper: "A", weight: "9" },
  ],
};

function emptyObservation(): ObservationDraft {
  return { lower: "", upper: "", weight: "1" };
}

export default function App() {
  const [layerText, setLayerText] = useState(SAMPLE.layers.join("\n"));
  const [observations, setObservations] = useState<ObservationDraft[]>(
    SAMPLE.observations,
  );
  const [errors, setErrors] = useState<{ pointer: string; message: string }[]>([]);
  const [result, setResult] = useState<SolutionResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [networkError, setNetworkError] = useState<string | null>(null);

  // Exact payload of the last successful solve; the profile endpoint is
  // invoked with these original ProblemIn fields plus the clicked target.
  const [submittedPayload, setSubmittedPayload] = useState<ProblemPayload | null>(null);

  // Derived placement-profile region; independent of the solve witness so
  // profile loading/errors never touch the original audit result.
  const [profileTarget, setProfileTarget] = useState<string | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileData, setProfileData] = useState<PlacementProfileResponse | null>(null);
  const [profileErrors, setProfileErrors] = useState<ValidationErrorItem[] | null>(null);
  // Latest click wins if two profile requests are in flight.
  const profileSeq = useRef(0);

  // Parsed layers are derived state, so reordering/editing cannot leave a
  // stale derived copy behind.
  const parsedLayers = useMemo(
    () =>
      layerText
        .split(/[\n,]/)
        .map((s) => s.trim())
        .filter((s) => s.length > 0),
    [layerText],
  );

  const updateObservation = (i: number, patch: Partial<ObservationDraft>) => {
    setObservations((prev) => prev.map((o, idx) => (idx === i ? { ...o, ...patch } : o)));
  };

  // Client-side pre-check mirrors the server rules and gives instant
  // feedback; the server remains the single authority (identical rules).
  const localErrors = useMemo(() => {
    const errs: { pointer: string; message: string }[] = [];
    if (parsedLayers.length < 2 || parsedLayers.length > 20) {
      errs.push({ pointer: "/layers", message: "图层数量须在 2 至 20 之间" });
    }
    const seen = new Map<string, number>();
    // Every non-empty listed token counts as "known" for dangling checks,
    // mirroring the server: a malformed listed id is reported at /layers/i,
    // not again as a dangling observation reference.
    const listed = new Set(parsedLayers);
    parsedLayers.forEach((id, i) => {
      if (!ID_RE.test(id)) {
        errs.push({ pointer: `/layers/${i}`, message: `标识 ${id} 不匹配 [A-Za-z0-9_-]{1,24}` });
      } else if (seen.has(id)) {
        errs.push({ pointer: `/layers/${i}`, message: `标识 ${id} 重复（首次位于 ${seen.get(id)}）` });
      } else {
        seen.set(id, i);
      }
    });
    if (observations.length === 0) {
      errs.push({ pointer: "/observations", message: "至少需要 1 条有向观察" });
    }
    const pairs = new Set<string>();
    observations.forEach((o, i) => {
      const p = (field: string) => `/observations/${i}/${field}`;
      const lowerKnown = !!o.lower && listed.has(o.lower);
      const upperKnown = !!o.upper && listed.has(o.upper);
      if (!lowerKnown) {
        errs.push({ pointer: p("lower"), message: `下层 ${o.lower || "(空)"} 不是已列出的图层` });
      }
      if (!upperKnown) {
        errs.push({ pointer: p("upper"), message: `上层 ${o.upper || "(空)"} 不是已列出的图层` });
      }
      if (lowerKnown && upperKnown && o.lower === o.upper) {
        errs.push({ pointer: `/observations/${i}`, message: "自环非法" });
      }
      const key = `${o.lower} ${o.upper}`;
      if (lowerKnown && upperKnown && o.lower !== o.upper) {
        if (pairs.has(key)) {
          errs.push({ pointer: `/observations/${i}`, message: `重复有向对 ${o.lower} → ${o.upper}` });
        } else {
          pairs.add(key);
        }
      }
      const w = Number(o.weight);
      if (!Number.isInteger(w) || w < 1 || w > 1_000_000) {
        errs.push({ pointer: p("weight"), message: "权重须为 1 至 1000000 的整数" });
      }
    });
    return errs.sort((a, b) => (a.pointer < b.pointer ? -1 : a.pointer > b.pointer ? 1 : 0));
  }, [parsedLayers, observations]);

  const handleSubmit = async () => {
    setLoading(true);
    // Any (re-)submission first clears stale output and stale errors: an
    // invalid answer never leaves an old optimum on screen. The derived
    // profile belongs to the previous witness, so it is cleared as well
    // (a fresh successful solve never carries an old target's profile).
    setResult(null);
    setSubmittedPayload(null);
    setProfileTarget(null);
    setProfileData(null);
    setProfileErrors(null);
    setProfileLoading(false);
    setNetworkError(null);
    if (localErrors.length > 0) {
      setErrors(localErrors);
      setLoading(false);
      return;
    }
    const payload: ProblemPayload = {
      layers: parsedLayers,
      observations: observations.map(
        (o): ObservationInput => ({ lower: o.lower, upper: o.upper, weight: Number(o.weight) }),
      ),
    };
    try {
      const solution = await solveProblem(payload);
      setResult(solution);
      setSubmittedPayload(payload);
      setErrors([]);
    } catch (err) {
      if (err instanceof SolveError) {
        setErrors(err.errors);
      } else {
        setNetworkError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setLoading(false);
    }
  };

  // Clicking a strip in the canonical witness derives that layer's profile
  // from the ORIGINAL ProblemIn payload; only the profile region changes.
  const handleLayerClick = async (layerId: string) => {
    if (!submittedPayload) return;
    const seq = ++profileSeq.current;
    setProfileTarget(layerId);
    setProfileLoading(true);
    setProfileData(null);
    setProfileErrors(null);
    try {
      const profile = await fetchPlacementProfile(submittedPayload, layerId);
      if (seq !== profileSeq.current) return; // a newer click superseded this one
      setProfileData(profile);
    } catch (err) {
      if (seq !== profileSeq.current) return;
      const errs: ValidationErrorItem[] =
        err instanceof SolveError
          ? err.errors
          : [{ pointer: "", message: err instanceof Error ? err.message : String(err) }];
      setProfileErrors(errs);
    } finally {
      if (seq === profileSeq.current) setProfileLoading(false);
    }
  };

  return (
    <div className="page">
      <header>
        <h1>多版套色木刻 · 图层叠压次序审计台</h1>
        <p className="subtitle">
          残存痕迹只给出「某色层应压在另一层之上」的有向证据；污损证据互相冲突时，
          本台以精确整数子集动态规划求<strong>全局最低违背代价</strong>的从底到顶排列，
          并列时按 ASCII 字节序返回最小的两条最优排列。
        </p>
      </header>

      <div className="layout">
        <section className="panel input-panel">
          <h2>① 录入</h2>

          <label className="field-label" htmlFor="layers">
            图层标识（每行一个，或用逗号分隔；2–20 个，唯一）
          </label>
          <textarea
            id="layers"
            rows={6}
            value={layerText}
            spellCheck={false}
            onChange={(e) => setLayerText(e.target.value)}
            placeholder={"A\nB\nC"}
          />
          <p className="hint">当前解析到 {parsedLayers.length} 个标识，须匹配 [A-Za-z0-9_-]{"{1,24}"}。</p>

          <div className="obs-header">
            <h3>有向观察（下层 → 上层，权重 1–1000000）</h3>
            <button type="button" className="btn small"
              onClick={() => setObservations((p) => [...p, emptyObservation()])}>
              + 添加观察
            </button>
          </div>

          <div className="obs-list">
            {observations.map((o, i) => (
              <div className="obs-row" key={i}>
                <span className="obs-idx">{i + 1}</span>
                <select value={o.lower} onChange={(e) => updateObservation(i, { lower: e.target.value })}>
                  <option value="">下层…</option>
                  {parsedLayers.map((id) => (
                    <option key={`lo-${id}`} value={id}>{id}</option>
                  ))}
                </select>
                <span className="arrow">→</span>
                <select value={o.upper} onChange={(e) => updateObservation(i, { upper: e.target.value })}>
                  <option value="">上层…</option>
                  {parsedLayers.map((id) => (
                    <option key={`up-${id}`} value={id}>{id}</option>
                  ))}
                </select>
                <input
                  className="weight-input"
                  type="number"
                  min={1}
                  max={1_000_000}
                  step={1}
                  value={o.weight}
                  onChange={(e) => updateObservation(i, { weight: e.target.value })}
                />
                <button type="button" className="btn ghost small"
                  onClick={() => setObservations((p) => p.filter((_, idx) => idx !== i))}>
                  删除
                </button>
              </div>
            ))}
            {observations.length === 0 && <p className="hint">暂无观察，请至少添加一条。</p>}
          </div>

          <div className="actions">
            <button type="button" className="btn primary" disabled={loading} onClick={handleSubmit}>
              {loading ? "计算中…" : "求全局最优次序"}
            </button>
            <button type="button" className="btn"
              onClick={() => {
                setLayerText(SAMPLE.layers.join("\n"));
                setObservations(SAMPLE.observations.map((o) => ({ ...o })));
              }}>
              载入示例
            </button>
            <button type="button" className="btn ghost"
              onClick={() => {
                setLayerText("");
                setObservations([]);
                setResult(null);
                setSubmittedPayload(null);
                setErrors([]);
                setNetworkError(null);
                setProfileTarget(null);
                setProfileData(null);
                setProfileErrors(null);
                setProfileLoading(false);
                profileSeq.current = 0;
              }}>
              清空
            </button>
          </div>
        </section>

        <section className="panel result-panel">
          <h2>② 审计结果</h2>

          {networkError && <div className="error-banner">网络或服务错误：{networkError}</div>}

          {errors.length > 0 && (
            <div className="errors">
              <h3>非法提交（{errors.length} 项，按 JSON Pointer 排序；旧结果已清除）</h3>
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

          {!result && errors.length === 0 && !networkError && (
            <p className="placeholder">提交后在此展示最优叠压轨道、逐条违背状态与可复算代价。</p>
          )}

          {result && (
            <div className="solution">
              <div className={`status-banner ${result.status}`}>
                {result.status === "unique" ? (
                  <>
                    <strong>唯一最优</strong>：总违背代价 <strong>{result.cost.toLocaleString()}</strong>
                  </>
                ) : (
                  <>
                    <strong>存在并列（ambiguous）</strong>：{ } 总代价 {result.cost.toLocaleString()}
                    ，以下为 ASCII 最小的两条不同最优排列
                  </>
                )}
              </div>

              <WitnessBlock
                title="规范见证 1（ASCII 最小最优排列，点击图层查看层位剖面）"
                witness={result.witness}
                onLayerClick={handleLayerClick}
                activeTarget={profileTarget}
              />

              {profileTarget && (
                <ProfilePanel
                  target={profileTarget}
                  loading={profileLoading}
                  profile={profileData}
                  errors={profileErrors}
                />
              )}

              {result.status === "ambiguous" && result.second_witness && (
                <details>
                  <summary>
                    规范见证 2（次小最优排列，代价同为 {result.second_cost?.toLocaleString()}）
                  </summary>
                  <WitnessBlock title="" witness={result.second_witness} nested />
                </details>
              )}
            </div>
          )}
        </section>
      </div>

      <footer>
        排列按从底到顶解释；观察 upper 未位于 lower 之后即计入其权重。
        输入行的重排不改变状态、代价与规范见证（服务端规范化输出）。
      </footer>
    </div>
  );
}

function WitnessBlock({
  title,
  witness,
  nested = false,
  onLayerClick,
  activeTarget,
}: {
  title: string;
  witness: SolutionResponse["witness"];
  nested?: boolean;
  onLayerClick?: (layerId: string) => void;
  activeTarget?: string | null;
}) {
  return (
    <div className={nested ? "witness nested" : "witness"}>
      {title && <h3>{title}</h3>}
      <p className="order-line">
        从底到顶：
        {witness.order.map((id, i) => (
          <span key={`${id}-${i}`} className="order-chip">
            {id}
            {i < witness.order.length - 1 && <em> ▲ </em>}
          </span>
        ))}
      </p>
      <StackTrack
        order={witness.order}
        rows={witness.observations}
        onLayerClick={onLayerClick}
        activeTarget={activeTarget}
      />
      <ObservationTable rows={witness.observations} totalCost={witness.cost} />
    </div>
  );
}
