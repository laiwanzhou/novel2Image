import { useState } from "react";
import { generatePrompt, getPromptDetail, listPromptHistory, PromptGeneration } from "../api";

export function PromptHistoryPage() {
  const [novelId, setNovelId] = useState("");
  const [chapterIndex, setChapterIndex] = useState("1");
  const [characterId, setCharacterId] = useState("");
  const [userRequest, setUserRequest] = useState("");
  const [prompts, setPrompts] = useState<PromptGeneration[]>([]);
  const [selected, setSelected] = useState<PromptGeneration | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  async function load() {
    if (!novelId.trim()) return;
    await run(async () => {
      const items = await listPromptHistory(novelId.trim());
      setPrompts(items);
      setSelected(items[0] ?? null);
    });
  }

  async function generate() {
    if (!novelId.trim() || !characterId.trim()) return;
    await run(async () => {
      const prompt = await generatePrompt({
        novel_id: novelId.trim(),
        chapter_index: Number(chapterIndex),
        character_id: characterId.trim(),
        user_request: userRequest || null,
      });
      setSelected(prompt);
      await load();
    });
  }

  async function selectPrompt(prompt: PromptGeneration) {
    await run(async () => {
      setSelected(await getPromptDetail(prompt.id));
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
        <div className="form-grid compact">
          <label>
            character_id
            <input value={characterId} onChange={(event) => setCharacterId(event.target.value)} />
          </label>
          <label>
            章节
            <input value={chapterIndex} onChange={(event) => setChapterIndex(event.target.value)} />
          </label>
          <label>
            用户要求
            <input value={userRequest} onChange={(event) => setUserRequest(event.target.value)} />
          </label>
        </div>
        <button onClick={generate} disabled={loading || !novelId.trim() || !characterId.trim()}>
          生成 Prompt
        </button>
        <table>
          <thead>
            <tr>
              <th>章节</th>
              <th>Type</th>
              <th>状态</th>
              <th>警告</th>
            </tr>
          </thead>
          <tbody>
            {prompts.map((prompt) => (
              <tr key={prompt.id} className={selected?.id === prompt.id ? "selected" : ""} onClick={() => selectPrompt(prompt)}>
                <td>{prompt.chapter_index}</td>
                <td>{prompt.prompt_type}</td>
                <td>{prompt.character_state_id ?? "-"}</td>
                <td>{prompt.warnings.length}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <aside className="panel details">
        <h2>Prompt 详情</h2>
        {selected ? (
          <>
            <h3>最终 Prompt</h3>
            <pre>{selected.final_prompt}</pre>
            <h3>证据快照</h3>
            <pre>{JSON.stringify(selected.evidence_snapshot, null, 2)}</pre>
          </>
        ) : (
          <p className="empty">尚未选择 prompt。</p>
        )}
        {message && <p className="status-line">{message}</p>}
      </aside>
    </section>
  );
}
