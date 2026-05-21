import { useState } from "react";
import { CharacterState, createInitialState, InitialStatePayload, listStates } from "../api";

export function CharacterStatesPage() {
  const [characterId, setCharacterId] = useState("");
  const [states, setStates] = useState<CharacterState[]>([]);
  const [selected, setSelected] = useState<CharacterState | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    novelId: "",
    chapterStart: "1",
    sourceChunkIds: "",
    appearance: "",
    personality: "",
    identity: "",
    motivation: "",
    relationshipSummary: "",
    visualKeywords: "",
    negativePrompt: "",
    confidence: "",
  });

  async function load() {
    if (!characterId.trim()) return;
    await run(async () => {
      const items = await listStates(characterId.trim());
      setStates(items);
      setSelected(items[0] ?? null);
    });
  }

  async function createState() {
    if (!characterId.trim() || !form.novelId.trim()) return;
    const payload: InitialStatePayload = {
      novel_id: form.novelId.trim(),
      chapter_start: Number(form.chapterStart),
      source_chunk_ids: splitList(form.sourceChunkIds),
      confidence: form.confidence ? Number(form.confidence) : null,
      fields: {
        appearance: form.appearance || null,
        personality: form.personality || null,
        identity: form.identity || null,
        motivation: form.motivation || null,
        relationship_summary: form.relationshipSummary || null,
        visual_keywords: splitList(form.visualKeywords),
        negative_prompt: form.negativePrompt || null,
      },
    };
    await run(async () => {
      await createInitialState(characterId.trim(), payload);
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
            character_id
            <input value={characterId} onChange={(event) => setCharacterId(event.target.value)} />
          </label>
          <button onClick={load} disabled={loading || !characterId.trim()}>
            加载
          </button>
        </div>
        <table>
          <thead>
            <tr>
              <th>章节范围</th>
              <th>状态</th>
              <th>身份</th>
              <th>视觉关键词</th>
            </tr>
          </thead>
          <tbody>
            {states.map((state) => (
              <tr key={state.id} className={selected?.id === state.id ? "selected" : ""} onClick={() => setSelected(state)}>
                <td>
                  {state.chapter_start}-{state.chapter_end ?? "未关闭"}
                </td>
                <td>{state.status}</td>
                <td>{state.identity ?? "-"}</td>
                <td>{state.visual_keywords.join(", ") || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="form-grid">
          <label>
            novel_id
            <input value={form.novelId} onChange={(event) => setForm({ ...form, novelId: event.target.value })} />
          </label>
          <label>
            起始章节
            <input value={form.chapterStart} onChange={(event) => setForm({ ...form, chapterStart: event.target.value })} />
          </label>
          <label>
            来源 chunk_ids
            <input value={form.sourceChunkIds} onChange={(event) => setForm({ ...form, sourceChunkIds: event.target.value })} />
          </label>
          <label>
            置信度
            <input value={form.confidence} onChange={(event) => setForm({ ...form, confidence: event.target.value })} />
          </label>
          <label>
            外貌
            <textarea value={form.appearance} onChange={(event) => setForm({ ...form, appearance: event.target.value })} />
          </label>
          <label>
            身份
            <textarea value={form.identity} onChange={(event) => setForm({ ...form, identity: event.target.value })} />
          </label>
          <label>
            性格
            <textarea value={form.personality} onChange={(event) => setForm({ ...form, personality: event.target.value })} />
          </label>
          <label>
            动机
            <textarea value={form.motivation} onChange={(event) => setForm({ ...form, motivation: event.target.value })} />
          </label>
          <label>
            关系摘要
            <textarea value={form.relationshipSummary} onChange={(event) => setForm({ ...form, relationshipSummary: event.target.value })} />
          </label>
          <label>
            视觉关键词
            <input value={form.visualKeywords} onChange={(event) => setForm({ ...form, visualKeywords: event.target.value })} />
          </label>
          <label>
            Negative Prompt
            <input value={form.negativePrompt} onChange={(event) => setForm({ ...form, negativePrompt: event.target.value })} />
          </label>
        </div>
        <button onClick={createState} disabled={loading || !characterId.trim() || !form.novelId.trim()}>
          创建初始状态
        </button>
      </div>
      <aside className="panel details">
        <h2>状态详情</h2>
        {selected ? <pre>{JSON.stringify(selected, null, 2)}</pre> : <p className="empty">尚未选择角色状态。</p>}
        {message && <p className="status-line">{message}</p>}
      </aside>
    </section>
  );
}

function splitList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}
