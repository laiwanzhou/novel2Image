import { useState } from "react";
import {
  acceptEventCandidate,
  acceptCandidate,
  acceptStateChangeCandidate,
  Candidate,
  ChapterSummary,
  CharacterSummary,
  CharacterState,
  chunkNovel,
  ChunkPreview,
  confirmAlias,
  confirmState,
  createCharacter,
  createInitialState,
  embedNovel,
  extractChapter,
  generatePrompt,
  getCrawledNovelPreview,
  getPromptDetail,
  getNovel,
  getProcessingStatus,
  InitialStatePayload,
  listCandidates,
  listChapterChunks,
  listChapters,
  listCharacters,
  listEventCandidates,
  listPromptHistory,
  listStateChangeCandidates,
  listStates,
  NovelSummary,
  ProcessingStatus,
  CrawledNovelPreview,
  EventCandidate,
  PromptGeneration,
  rejectEventCandidate,
  rejectCandidate,
  rejectStateChangeCandidate,
  StateChangeCandidate,
} from "../api";

export function NovelWorkspacePage() {
  const [novelId, setNovelId] = useState("");
  const [novel, setNovel] = useState<NovelSummary | null>(null);
  const [status, setStatus] = useState<ProcessingStatus | null>(null);
  const [chapters, setChapters] = useState<ChapterSummary[]>([]);
  const [selectedChapter, setSelectedChapter] = useState<ChapterSummary | null>(null);
  const [chunks, setChunks] = useState<ChunkPreview[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [characters, setCharacters] = useState<CharacterSummary[]>([]);
  const [selectedCharacterId, setSelectedCharacterId] = useState("");
  const [states, setStates] = useState<CharacterState[]>([]);
  const [selectedState, setSelectedState] = useState<CharacterState | null>(null);
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(null);
  const [eventCandidates, setEventCandidates] = useState<EventCandidate[]>([]);
  const [stateChangeCandidates, setStateChangeCandidates] = useState<StateChangeCandidate[]>([]);
  const [prompts, setPrompts] = useState<PromptGeneration[]>([]);
  const [selectedPrompt, setSelectedPrompt] = useState<PromptGeneration | null>(null);
  const [crawledPreview, setCrawledPreview] = useState<CrawledNovelPreview | null>(null);
  const [crawledPreviewError, setCrawledPreviewError] = useState("");
  const [selectedPreviewChapterIndex, setSelectedPreviewChapterIndex] = useState(1);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [reviewer, setReviewer] = useState("admin");
  const [reviewNote, setReviewNote] = useState("");
  const [targetCharacterId, setTargetCharacterId] = useState("");
  const [userRequest, setUserRequest] = useState("");
  const [manualCharacterForm, setManualCharacterForm] = useState({
    canonicalName: "塔莉亚·罗诺威",
    description: "第 1 章登场的混血魔族，隆多兰地下城继承者。",
    sourceChunkIds: "",
    confidence: "",
    status: "confirmed" as "candidate" | "confirmed",
  });
  const [initialStateForm, setInitialStateForm] = useState({
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

  async function loadWorkspace() {
    const id = novelId.trim();
    if (!id) return;
    setLoading(true);
    setMessage("");
    try {
      const [novelResult, statusResult, chapterResult, candidateResult, characterResult, promptResult] =
        await Promise.all([
          getNovel(id),
          getProcessingStatus(id),
          listChapters(id),
          listCandidates(id),
          listCharacters(id, "confirmed"),
          listPromptHistory(id),
        ]);
      setNovel(novelResult);
      setStatus(statusResult);
      setChapters(chapterResult);
      setCandidates(candidateResult);
      setCharacters(characterResult);
      setPrompts(promptResult);
      try {
        setCrawledPreview(await getCrawledNovelPreview(selectedPreviewChapterIndex));
        setCrawledPreviewError("");
      } catch (previewError) {
        setCrawledPreview(null);
        setCrawledPreviewError(
          previewError instanceof Error ? previewError.message : "原文预览加载失败。",
        );
      }
      setSelectedCandidate(candidateResult[0] ?? null);
      setSelectedPrompt(promptResult[0] ?? null);
      const nextChapter =
        selectedChapter && chapterResult.some((chapter) => chapter.id === selectedChapter.id)
          ? selectedChapter
          : chapterResult[0] ?? null;
      setSelectedChapter(nextChapter);
      const nextCharacterId =
        selectedCharacterId && characterResult.some((character) => character.id === selectedCharacterId)
          ? selectedCharacterId
          : characterResult[0]?.id ?? "";
      setSelectedCharacterId(nextCharacterId);
      if (nextCharacterId) {
        await loadStatesForCharacter(nextCharacterId);
      } else {
        setStates([]);
        setSelectedState(null);
      }
      if (nextChapter) {
        setChunks(await listChapterChunks(nextChapter.id));
      } else {
        setChunks([]);
      }
      await loadKnowledgeReviewCandidates(id, nextChapter?.id);
      setMessage("工作台已加载。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "请求失败。");
    } finally {
      setLoading(false);
    }
  }

  async function selectChapter(chapter: ChapterSummary) {
    setSelectedChapter(chapter);
    setLoading(true);
    setMessage("");
    try {
      setChunks(await listChapterChunks(chapter.id));
      await loadKnowledgeReviewCandidates(novelId.trim(), chapter.id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "请求失败。");
    } finally {
      setLoading(false);
    }
  }

  async function refreshWorkspaceParts(
    options: { refreshCandidates?: boolean; refreshPrompts?: boolean; selectedPromptIdToKeep?: string } = {},
  ) {
    const id = novelId.trim();
    if (!id) return;
    const [statusResult, chapterResult, characterResult] = await Promise.all([
      getProcessingStatus(id),
      listChapters(id),
      listCharacters(id, "confirmed"),
    ]);
    setStatus(statusResult);
    setChapters(chapterResult);
    setCharacters(characterResult);
    const currentChapter = selectedChapter
      ? chapterResult.find((chapter) => chapter.id === selectedChapter.id) ?? chapterResult[0] ?? null
      : chapterResult[0] ?? null;
    setSelectedChapter(currentChapter);
    setChunks(currentChapter ? await listChapterChunks(currentChapter.id) : []);
    if (options.refreshCandidates) {
      const candidateResult = await listCandidates(id);
      setCandidates(candidateResult);
      setSelectedCandidate(candidateResult[0] ?? null);
      await loadKnowledgeReviewCandidates(id, currentChapter?.id);
    }
    if (options.refreshPrompts) {
      const promptResult = await listPromptHistory(id);
      setPrompts(promptResult);
      setSelectedPrompt(
        options.selectedPromptIdToKeep
          ? promptResult.find((prompt) => prompt.id === options.selectedPromptIdToKeep) ?? selectedPrompt
          : promptResult[0] ?? null,
      );
    }
    if (selectedCharacterId) {
      await loadStatesForCharacter(selectedCharacterId);
    }
  }

  async function runAction(successMessage: string, task: () => Promise<void>) {
    setLoading(true);
    setMessage("");
    try {
      await task();
      setMessage(successMessage);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "请求失败。");
    } finally {
      setLoading(false);
    }
  }

  async function loadStatesForCharacter(characterId: string) {
    const items = await listStates(characterId);
    setStates(items);
    setSelectedState(items[0] ?? null);
  }

  async function loadKnowledgeReviewCandidates(id = novelId.trim(), chapterId = selectedChapter?.id) {
    if (!id) return;
    const filters = chapterId ? { chapter_id: chapterId, status: "candidate" } : { status: "candidate" };
    const [events, changes] = await Promise.all([listEventCandidates(id, filters), listStateChangeCandidates(id, filters)]);
    setEventCandidates(events);
    setStateChangeCandidates(changes);
  }

  async function selectCharacter(characterId: string) {
    setSelectedCharacterId(characterId);
    setLoading(true);
    setMessage("");
    try {
      if (characterId) {
        await loadStatesForCharacter(characterId);
      } else {
        setStates([]);
        setSelectedState(null);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Request failed.");
    } finally {
      setLoading(false);
    }
  }

  async function runChunkNovel() {
    await runAction("小说 chunk 已生成。", async () => {
      await chunkNovel(novelId.trim());
      await refreshWorkspaceParts();
    });
  }

  async function runEmbedNovel() {
    await runAction("缺失 embedding 的 chunks 已处理。", async () => {
      await embedNovel(novelId.trim());
      await refreshWorkspaceParts();
    });
  }

  async function runExtractChapter() {
    if (!selectedChapter) return;
    await runAction("单章抽取已完成。", async () => {
      await extractChapter(selectedChapter.id);
      await refreshWorkspaceParts({ refreshCandidates: true });
    });
  }

  async function reviewEventCandidate(candidate: EventCandidate, action: "accept" | "reject") {
    await runAction("事件候选审核已保存。", async () => {
      if (action === "accept") {
        await acceptEventCandidate(candidate.id, reviewer, reviewNote);
      } else {
        await rejectEventCandidate(candidate.id, reviewer, reviewNote);
      }
      await refreshWorkspaceParts({ refreshCandidates: true });
    });
  }

  async function reviewStateChangeCandidate(candidate: StateChangeCandidate, action: "accept" | "reject") {
    await runAction("状态变更候选审核已保存。", async () => {
      if (action === "accept") {
        await acceptStateChangeCandidate(candidate.id, reviewer, reviewNote);
      } else {
        await rejectStateChangeCandidate(candidate.id, reviewer, reviewNote);
      }
      await refreshWorkspaceParts({ refreshCandidates: true });
    });
  }

  async function reviewSelectedCandidate(action: "accept" | "reject") {
    if (!selectedCandidate) return;
    await runAction("候选审核已保存。", async () => {
      if (action === "accept") {
        await acceptCandidate(selectedCandidate.target_type, selectedCandidate.id, reviewer, reviewNote);
      } else {
        await rejectCandidate(selectedCandidate.target_type, selectedCandidate.id, reviewer, reviewNote);
      }
      await refreshWorkspaceParts({ refreshCandidates: true });
    });
  }

  async function mergeSelectedAlias() {
    if (!selectedCandidate || selectedCandidate.target_type !== "alias" || !targetCharacterId.trim()) return;
    await runAction("别名已确认。", async () => {
      await confirmAlias(selectedCandidate.id, targetCharacterId.trim(), reviewer, reviewNote);
      await refreshWorkspaceParts({ refreshCandidates: true });
    });
  }

  async function createManualCharacter() {
    if (!novelId.trim() || !manualCharacterForm.canonicalName.trim()) return;
    await runAction("角色已创建。", async () => {
      const character = await createCharacter(novelId.trim(), {
        canonical_name: manualCharacterForm.canonicalName.trim(),
        description: manualCharacterForm.description.trim() || null,
        source_chunk_ids: splitList(manualCharacterForm.sourceChunkIds),
        confidence: manualCharacterForm.confidence ? Number(manualCharacterForm.confidence) : null,
        status: manualCharacterForm.status,
      });
      await refreshWorkspaceParts({ refreshCandidates: true });
      if (character.status === "confirmed") {
        setSelectedCharacterId(character.id);
        await loadStatesForCharacter(character.id);
      }
    });
  }

  async function confirmSelectedState() {
    if (!selectedState) return;
    await runAction("角色状态已确认。", async () => {
      const state = await confirmState(selectedState.id, reviewer, reviewNote);
      await refreshWorkspaceParts();
      await loadStatesForCharacter(state.character_id);
    });
  }

  async function createInitialStateCandidate() {
    if (!selectedCharacterId || !novelId.trim()) return;
    const payload: InitialStatePayload = {
      novel_id: novelId.trim(),
      chapter_start: Number(initialStateForm.chapterStart),
      source_chunk_ids: splitList(initialStateForm.sourceChunkIds),
      confidence: initialStateForm.confidence ? Number(initialStateForm.confidence) : null,
      fields: {
        appearance: initialStateForm.appearance || null,
        personality: initialStateForm.personality || null,
        identity: initialStateForm.identity || null,
        motivation: initialStateForm.motivation || null,
        relationship_summary: initialStateForm.relationshipSummary || null,
        visual_keywords: splitList(initialStateForm.visualKeywords),
        negative_prompt: initialStateForm.negativePrompt || null,
      },
    };
    await runAction("初始状态候选已创建。", async () => {
      await createInitialState(selectedCharacterId, payload);
      await refreshWorkspaceParts();
      await loadStatesForCharacter(selectedCharacterId);
    });
  }

  async function generateWorkspacePrompt() {
    if (!selectedChapter || !selectedCharacterId || !novelId.trim()) return;
    await runAction("Prompt 已生成。", async () => {
      const prompt = await generatePrompt({
        novel_id: novelId.trim(),
        chapter_index: selectedChapter.chapter_index,
        character_id: selectedCharacterId,
        user_request: userRequest || null,
      });
      setSelectedPrompt(prompt);
      await refreshWorkspaceParts({ refreshPrompts: true, selectedPromptIdToKeep: prompt.id });
    });
  }

  async function selectPrompt(prompt: PromptGeneration) {
    await runAction("Prompt 详情已加载。", async () => {
      setSelectedPrompt(await getPromptDetail(prompt.id));
    });
  }

  async function selectPreviewChapter(chapterIndex: number) {
    setSelectedPreviewChapterIndex(chapterIndex);
    try {
      setCrawledPreview(await getCrawledNovelPreview(chapterIndex));
      setCrawledPreviewError("");
    } catch (previewError) {
      setCrawledPreview(null);
      setCrawledPreviewError(previewError instanceof Error ? previewError.message : "原文预览加载失败。");
    }
  }

  return (
    <section className="workbench workspace-grid">
      <div className="panel workspace-wide">
        <div className="toolbar">
          <label>
            novel_id
            <input value={novelId} onChange={(event) => setNovelId(event.target.value)} />
          </label>
          <button onClick={loadWorkspace} disabled={loading || !novelId.trim()}>
            加载工作台
          </button>
        </div>
        {message && <p className="status-line">{message}</p>}
        <div className="summary-grid">
          <Summary label="书名" value={novel?.title ?? "-"} />
          <Summary label="作者" value={novel?.author ?? "-"} />
          <Summary label="来源类型" value={novel?.source_type ?? "-"} />
          <Summary label="语言" value={novel?.language ?? "-"} />
          <Summary label="章节数" value={status?.chapter_count ?? "-"} />
          <Summary label="Chunks" value={status?.chunk_count ?? "-"} />
          <Summary label="Embedding" value={status ? `${status.embedded_count}/${status.chunk_count}` : "-"} />
          <Summary label="Prompt 记录" value={status?.prompt_generation_count ?? "-"} />
        </div>
      </div>

      <div className="panel workspace-wide">
        <h2>原文文件（Operator 爬取预览）</h2>
        <p className="empty">
          这里显示的是只读的爬取预览文件来源，不是当前输入 novel_id 的数据库原文。
        </p>
        {crawledPreview ? (
          <dl>
            <dt>数据来源</dt>
            <dd>Sample/Crawled Preview（独立于当前数据库 novel）</dd>
            <dt>novel.md</dt>
            <dd>{crawledPreview.novel_md_path}</dd>
            <dt>manifest.json</dt>
            <dd>{crawledPreview.manifest_path}</dd>
          </dl>
        ) : crawledPreviewError ? (
          <p className="empty">原文预览暂不可用：{crawledPreviewError}</p>
        ) : (
          <p className="empty">加载工作台后显示当前 operator 输出文件路径。</p>
        )}
      </div>

      <div className="panel workspace-main">
        <h2>章节与处理状态</h2>
        <div className="button-row">
          <button onClick={runChunkNovel} disabled={loading || !novelId.trim()}>
            生成 Chunks
          </button>
          <button onClick={runEmbedNovel} disabled={loading || !novelId.trim()}>
            补齐 Embedding
          </button>
          <button onClick={runExtractChapter} disabled={loading || !selectedChapter}>
            抽取当前章节
          </button>
        </div>
        <table>
          <thead>
            <tr>
              <th>序号</th>
              <th>标题</th>
              <th>字数</th>
              <th>Chunks</th>
              <th>Embedding</th>
            </tr>
          </thead>
          <tbody>
            {chapters.map((chapter) => (
              <tr
                key={chapter.id}
                className={selectedChapter?.id === chapter.id ? "selected" : ""}
                onClick={() => selectChapter(chapter)}
              >
                <td>{chapter.chapter_index}</td>
                <td>{chapter.title}</td>
                <td>{chapter.word_count}</td>
                <td>{chapter.chunk_count}</td>
                <td>{chapter.embedded_count}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <h2>当前章节 Chunks</h2>
        <table>
          <thead>
            <tr>
              <th>Chunk</th>
              <th>字符数</th>
              <th>Embedding</th>
              <th>预览</th>
            </tr>
          </thead>
          <tbody>
            {chunks.map((chunk) => (
              <tr key={chunk.id}>
                <td>{chunk.chunk_index}</td>
                <td>{chunk.char_count}</td>
                <td>{chunk.has_embedding ? "是" : "否"}</td>
                <td>{chunk.text_preview}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <aside className="panel workspace-side">
        <h2>处理概览</h2>
        {status ? (
          <dl>
            <dt>缺失 Embedding</dt>
            <dd>{status.missing_embedding_count}</dd>
            <dt>候选角色</dt>
            <dd>{status.candidate_character_count}</dd>
            <dt>已确认角色</dt>
            <dd>{status.confirmed_character_count}</dd>
            <dt>候选别名</dt>
            <dd>{status.candidate_alias_count}</dd>
            <dt>候选事件</dt>
            <dd>{status.candidate_event_count}</dd>
            <dt>候选状态变更</dt>
            <dd>{status.candidate_state_change_count}</dd>
            <dt>候选角色状态</dt>
            <dd>{status.candidate_state_count}</dd>
            <dt>已确认角色状态</dt>
            <dd>{status.confirmed_state_count}</dd>
          </dl>
        ) : (
          <p className="empty">加载小说后查看处理状态。</p>
        )}
      </aside>

      <div className="panel workspace-card">
        <h2>原文预览（Sample/Crawled Preview）</h2>
        {crawledPreview ? (
          <>
            <p className="empty">
              此区块来自 `/operator/crawled-novel-preview`，用于检查爬取文件格式；它不随上方 novel_id 切换。
              当前数据库小说请以上方“章节与处理状态”为准。
            </p>
            <div className="summary-grid compact-summary">
              <Summary label="书名" value={crawledPreview.title} />
              <Summary label="预览章节数" value={crawledPreview.chapter_count} />
            </div>
            <label>
              选择原文章节
              <select
                value={crawledPreview.selected_chapter_index}
                onChange={(event) => selectPreviewChapter(Number(event.target.value))}
              >
                {crawledPreview.chapters.map((chapter) => (
                  <option key={chapter.index} value={chapter.index}>
                    {chapter.index}: {chapter.title}
                  </option>
                ))}
              </select>
            </label>
            <table>
              <thead>
                <tr>
                  <th>序号</th>
                  <th>标题</th>
                  <th>字数</th>
                  <th>分页数</th>
                </tr>
              </thead>
              <tbody>
                {crawledPreview.chapters.map((chapter) => (
                  <tr key={chapter.index}>
                    <td>{chapter.index}</td>
                    <td>{chapter.title}</td>
                    <td>{chapter.word_count}</td>
                    <td>{chapter.page_urls.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3>{crawledPreview.selected_chapter_title}</h3>
            <pre>{crawledPreview.chapter_text}</pre>
          </>
        ) : crawledPreviewError ? (
          <p className="empty">原文预览暂不可用：{crawledPreviewError}</p>
        ) : (
          <p className="empty">加载工作台后显示爬取原文的只读预览。</p>
        )}
      </div>

      <div className="panel workspace-card">
        <h2>候选审核</h2>
        <p className="empty">已加载 {candidates.length} 条候选记录。</p>
        <table>
          <thead>
            <tr>
              <th>类型</th>
              <th>名称</th>
              <th>置信度</th>
            </tr>
          </thead>
          <tbody>
            {candidates.slice(0, 6).map((candidate) => (
              <tr
                key={candidate.id}
                className={selectedCandidate?.id === candidate.id ? "selected" : ""}
                onClick={() => setSelectedCandidate(candidate)}
              >
                <td>{candidate.target_type}</td>
                <td>{candidate.label}</td>
                <td>{candidate.confidence ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <label>
          审核人
          <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} />
        </label>
        <label>
          审核备注
          <input value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} />
        </label>
        <label>
          别名目标角色
          <select value={targetCharacterId} onChange={(event) => setTargetCharacterId(event.target.value)}>
            <option value="">选择已确认角色</option>
            {characters.map((character) => (
              <option key={character.id} value={character.id}>
                {character.canonical_name}
              </option>
            ))}
          </select>
        </label>
        <div className="button-row">
          <button
            onClick={() => reviewSelectedCandidate("accept")}
            disabled={loading || !selectedCandidate || selectedCandidate.target_type !== "character"}
          >
            接受角色
          </button>
          <button
            onClick={mergeSelectedAlias}
            disabled={loading || !selectedCandidate || selectedCandidate.target_type !== "alias" || !targetCharacterId}
          >
            确认别名
          </button>
          <button onClick={() => reviewSelectedCandidate("reject")} disabled={loading || !selectedCandidate}>
            废弃
          </button>
        </div>
        <h3>事件候选</h3>
        <p className="empty">当前章节已加载 {eventCandidates.length} 条 CharacterEvent candidate。</p>
        <table>
          <thead>
            <tr>
              <th>角色</th>
              <th>章节</th>
              <th>类型</th>
              <th>长期变化</th>
              <th>摘要</th>
              <th>置信度</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {eventCandidates.map((candidate) => (
              <tr key={candidate.id}>
                <td>{candidate.character_name ?? candidate.character_id ?? "-"}</td>
                <td>{candidate.chapter_index}</td>
                <td>{candidate.event_type}</td>
                <td>{candidate.is_long_term_change ? "是" : "否"}</td>
                <td>
                  <strong>{candidate.event_summary}</strong>
                  <p>{candidate.explanation ?? "-"}</p>
                  <p>影响字段：{candidate.affected_fields.join(", ") || "-"}</p>
                  <details>
                    <summary>source_chunk_ids</summary>
                    <pre>{candidate.source_chunk_ids.join("\n")}</pre>
                  </details>
                </td>
                <td>{candidate.confidence ?? "-"}</td>
                <td>
                  <div className="button-row">
                    <button onClick={() => reviewEventCandidate(candidate, "accept")} disabled={loading}>
                      接受
                    </button>
                    <button onClick={() => reviewEventCandidate(candidate, "reject")} disabled={loading}>
                      废弃
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <h3>状态变更候选</h3>
        <p className="empty">当前章节已加载 {stateChangeCandidates.length} 条 CharacterStateChange candidate。</p>
        <table>
          <thead>
            <tr>
              <th>角色</th>
              <th>章节</th>
              <th>字段变更</th>
              <th>置信度</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {stateChangeCandidates.map((candidate) => (
              <tr key={candidate.id}>
                <td>{candidate.character_name ?? candidate.character_id ?? "-"}</td>
                <td>{candidate.chapter_index}</td>
                <td>
                  <pre>{JSON.stringify(candidate.changed_fields, null, 2)}</pre>
                  <p>{candidate.explanation ?? "-"}</p>
                  <details>
                    <summary>source_chunk_ids</summary>
                    <pre>{candidate.source_chunk_ids.join("\n")}</pre>
                  </details>
                </td>
                <td>{candidate.confidence ?? "-"}</td>
                <td>
                  <div className="button-row">
                    <button onClick={() => reviewStateChangeCandidate(candidate, "accept")} disabled={loading}>
                      接受
                    </button>
                    <button onClick={() => reviewStateChangeCandidate(candidate, "reject")} disabled={loading}>
                      废弃
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <h3>手动创建角色</h3>
        <div className="form-grid compact">
          <label>
            角色名
            <input
              value={manualCharacterForm.canonicalName}
              onChange={(event) => setManualCharacterForm({ ...manualCharacterForm, canonicalName: event.target.value })}
            />
          </label>
          <label>
            状态
            <select
              value={manualCharacterForm.status}
              onChange={(event) =>
                setManualCharacterForm({
                  ...manualCharacterForm,
                  status: event.target.value as "candidate" | "confirmed",
                })
              }
            >
              <option value="candidate">candidate</option>
              <option value="confirmed">confirmed</option>
            </select>
          </label>
          <label>
            置信度
            <input
              value={manualCharacterForm.confidence}
              onChange={(event) => setManualCharacterForm({ ...manualCharacterForm, confidence: event.target.value })}
            />
          </label>
          <label>
            来源 chunk_ids
            <input
              value={manualCharacterForm.sourceChunkIds}
              onChange={(event) => setManualCharacterForm({ ...manualCharacterForm, sourceChunkIds: event.target.value })}
            />
          </label>
        </div>
        <label>
          描述
          <textarea
            value={manualCharacterForm.description}
            onChange={(event) => setManualCharacterForm({ ...manualCharacterForm, description: event.target.value })}
          />
        </label>
        <button onClick={createManualCharacter} disabled={loading || !novelId.trim() || !manualCharacterForm.canonicalName.trim()}>
          创建角色
        </button>
      </div>

      <div className="panel workspace-card">
        <h2>角色状态</h2>
        <label>
          已确认角色
          <select value={selectedCharacterId} onChange={(event) => selectCharacter(event.target.value)}>
            <option value="">选择角色</option>
            {characters.map((character) => (
              <option key={character.id} value={character.id}>
                {character.canonical_name}
              </option>
            ))}
          </select>
        </label>
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
              <tr
                key={state.id}
                className={selectedState?.id === state.id ? "selected" : ""}
                onClick={() => setSelectedState(state)}
              >
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
        {selectedState && <pre>{JSON.stringify(selectedState, null, 2)}</pre>}
        <button onClick={confirmSelectedState} disabled={loading || !selectedState || selectedState.status !== "candidate"}>
          确认选中状态
        </button>
        <div className="form-grid">
          <label>
            起始章节
            <input
              value={initialStateForm.chapterStart}
              onChange={(event) => setInitialStateForm({ ...initialStateForm, chapterStart: event.target.value })}
            />
          </label>
          <label>
            来源 chunk_ids
            <input
              value={initialStateForm.sourceChunkIds}
              onChange={(event) => setInitialStateForm({ ...initialStateForm, sourceChunkIds: event.target.value })}
            />
          </label>
          <label>
            外貌
            <textarea
              value={initialStateForm.appearance}
              onChange={(event) => setInitialStateForm({ ...initialStateForm, appearance: event.target.value })}
            />
          </label>
          <label>
            身份
            <textarea
              value={initialStateForm.identity}
              onChange={(event) => setInitialStateForm({ ...initialStateForm, identity: event.target.value })}
            />
          </label>
          <label>
            性格
            <textarea
              value={initialStateForm.personality}
              onChange={(event) => setInitialStateForm({ ...initialStateForm, personality: event.target.value })}
            />
          </label>
          <label>
            动机
            <textarea
              value={initialStateForm.motivation}
              onChange={(event) => setInitialStateForm({ ...initialStateForm, motivation: event.target.value })}
            />
          </label>
          <label>
            关系摘要
            <textarea
              value={initialStateForm.relationshipSummary}
              onChange={(event) => setInitialStateForm({ ...initialStateForm, relationshipSummary: event.target.value })}
            />
          </label>
          <label>
            视觉关键词
            <input
              value={initialStateForm.visualKeywords}
              onChange={(event) => setInitialStateForm({ ...initialStateForm, visualKeywords: event.target.value })}
            />
          </label>
          <label>
            Negative Prompt
            <input
              value={initialStateForm.negativePrompt}
              onChange={(event) => setInitialStateForm({ ...initialStateForm, negativePrompt: event.target.value })}
            />
          </label>
          <label>
            置信度
            <input
              value={initialStateForm.confidence}
              onChange={(event) => setInitialStateForm({ ...initialStateForm, confidence: event.target.value })}
            />
          </label>
        </div>
        <button
          onClick={createInitialStateCandidate}
          disabled={loading || !selectedCharacterId || !initialStateForm.sourceChunkIds.trim()}
        >
          创建初始状态候选
        </button>
      </div>

      <div className="panel workspace-card">
        <h2>Prompt 实验台</h2>
        <div className="form-grid compact">
          <label>
            章节
            <select value={selectedChapter?.id ?? ""} onChange={(event) => {
              const chapter = chapters.find((item) => item.id === event.target.value);
              if (chapter) selectChapter(chapter);
            }}>
              <option value="">选择章节</option>
              {chapters.map((chapter) => (
                <option key={chapter.id} value={chapter.id}>
                  {chapter.chapter_index}: {chapter.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            角色
            <select value={selectedCharacterId} onChange={(event) => selectCharacter(event.target.value)}>
              <option value="">选择角色</option>
              {characters.map((character) => (
                <option key={character.id} value={character.id}>
                  {character.canonical_name}
                </option>
              ))}
            </select>
          </label>
          <label>
            用户要求
            <input value={userRequest} onChange={(event) => setUserRequest(event.target.value)} />
          </label>
        </div>
        <button onClick={generateWorkspacePrompt} disabled={loading || !selectedChapter || !selectedCharacterId}>
          生成 Prompt
        </button>
        <p className="empty">已加载 {prompts.length} 条 prompt 记录。</p>
        <table>
          <thead>
            <tr>
              <th>章节</th>
              <th>Type</th>
              <th>警告</th>
            </tr>
          </thead>
          <tbody>
            {prompts.slice(0, 6).map((prompt) => (
              <tr
                key={prompt.id}
                className={selectedPrompt?.id === prompt.id ? "selected" : ""}
                onClick={() => selectPrompt(prompt)}
              >
                <td>{prompt.chapter_index}</td>
                <td>{prompt.prompt_type}</td>
                <td>{prompt.warnings.length}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {selectedPrompt && (
          <>
            <h3>最终 Prompt</h3>
            <pre>{selectedPrompt.final_prompt}</pre>
            <h3>Negative Prompt</h3>
            <pre>{selectedPrompt.negative_prompt || "-"}</pre>
            <h3>警告</h3>
            <pre>{JSON.stringify(selectedPrompt.warnings, null, 2)}</pre>
            <h3>证据快照</h3>
            <pre>{JSON.stringify(selectedPrompt.evidence_snapshot, null, 2)}</pre>
          </>
        )}
      </div>
    </section>
  );
}

function splitList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function Summary({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="summary-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
