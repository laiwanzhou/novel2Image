import { useState } from "react";
import { acceptCandidate, Candidate, confirmAlias, listCandidates, rejectCandidate } from "../api";

export function CandidateReviewPage() {
  const [novelId, setNovelId] = useState("");
  const [reviewer, setReviewer] = useState("admin");
  const [note, setNote] = useState("");
  const [targetCharacterId, setTargetCharacterId] = useState("");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  async function load() {
    if (!novelId.trim()) return;
    await run(async () => {
      const items = await listCandidates(novelId.trim());
      setCandidates(items);
      setSelected(items[0] ?? null);
    });
  }

  async function review(action: "accept" | "reject") {
    if (!selected) return;
    await run(async () => {
      if (action === "accept") {
        await acceptCandidate(selected.target_type, selected.id, reviewer, note);
      } else {
        await rejectCandidate(selected.target_type, selected.id, reviewer, note);
      }
      await load();
    });
  }

  async function mergeAlias() {
    if (!selected || selected.target_type !== "alias" || !targetCharacterId.trim()) return;
    await run(async () => {
      await confirmAlias(selected.id, targetCharacterId.trim(), reviewer, note);
      await load();
    });
  }

  async function run(task: () => Promise<void>) {
    setLoading(true);
    setMessage("");
    try {
      await task();
      setMessage("已保存。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "请求失败。");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="workbench two-column">
      <div className="panel">
        <div className="toolbar">
          <label>
            novel_id
            <input value={novelId} onChange={(event) => setNovelId(event.target.value)} />
          </label>
          <button onClick={load} disabled={loading || !novelId.trim()}>
            加载
          </button>
        </div>
        <table>
          <thead>
            <tr>
              <th>类型</th>
              <th>名称</th>
              <th>状态</th>
              <th>置信度</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((candidate) => (
              <tr
                key={candidate.id}
                className={selected?.id === candidate.id ? "selected" : ""}
                onClick={() => setSelected(candidate)}
              >
                <td>{candidate.target_type}</td>
                <td>{candidate.label}</td>
                <td>{candidate.status}</td>
                <td>{candidate.confidence ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <aside className="panel details">
        <h2>候选详情</h2>
        {selected ? (
          <>
            <dl>
              <dt>ID</dt>
              <dd>{selected.id}</dd>
              <dt>来源 chunks</dt>
              <dd>{selected.source_chunk_ids.join(", ") || "-"}</dd>
              <dt>审核备注</dt>
              <dd>{selected.review_note || "-"}</dd>
            </dl>
            <label>
              审核人
              <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} />
            </label>
            <label>
              备注
              <textarea value={note} onChange={(event) => setNote(event.target.value)} />
            </label>
            {selected.target_type === "alias" && (
              <label>
                目标 character_id
                <input value={targetCharacterId} onChange={(event) => setTargetCharacterId(event.target.value)} />
              </label>
            )}
            <div className="button-row">
              <button onClick={() => review("accept")} disabled={loading || selected.target_type !== "character"}>
                接受
              </button>
              <button onClick={mergeAlias} disabled={loading || selected.target_type !== "alias" || !targetCharacterId.trim()}>
                合并别名
              </button>
              <button className="danger" onClick={() => review("reject")} disabled={loading}>
                废弃
              </button>
            </div>
          </>
        ) : (
          <p className="empty">尚未选择候选项。</p>
        )}
        {message && <p className="status-line">{message}</p>}
      </aside>
    </section>
  );
}
