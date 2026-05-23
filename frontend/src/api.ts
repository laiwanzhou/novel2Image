const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export type Candidate = {
  target_type: "character" | "alias";
  id: string;
  novel_id: string;
  character_id?: string | null;
  label: string;
  alias_type?: string;
  status: string;
  source_chunk_ids: string[];
  confidence?: number | null;
  review_note?: string | null;
};

export type EventCandidate = {
  id: string;
  novel_id: string;
  character_id: string | null;
  character_name: string | null;
  chapter_id: string;
  chapter_index: number;
  event_summary: string;
  event_type: string;
  is_long_term_change: boolean;
  affected_fields: string[];
  source_chunk_ids: string[];
  confidence: number | null;
  explanation: string | null;
  status: string;
  reviewed_at?: string | null;
  reviewed_by?: string | null;
  review_note?: string | null;
};

export type StateChangeCandidate = {
  id: string;
  novel_id: string;
  character_id: string | null;
  character_name: string | null;
  event_id: string | null;
  chapter_id: string;
  chapter_index: number;
  changed_fields: Array<Record<string, unknown>>;
  source_chunk_ids: string[];
  confidence: number | null;
  explanation: string | null;
  status: string;
  reviewed_at?: string | null;
  reviewed_by?: string | null;
  review_note?: string | null;
};

export type CharacterState = {
  id: string;
  novel_id: string;
  character_id: string;
  chapter_start: number;
  chapter_end: number | null;
  appearance: string | null;
  personality: string | null;
  identity: string | null;
  motivation: string | null;
  relationship_summary: string | null;
  visual_keywords: string[];
  negative_prompt: string | null;
  source_chapters: number[];
  source_chunk_ids: string[];
  confidence: number | null;
  status: string;
  reviewed_at?: string | null;
  reviewed_by?: string | null;
  review_note?: string | null;
};

export type NovelSummary = {
  id: string;
  title: string;
  author: string | null;
  source_type: string;
  language: string;
  imported_at: string | null;
  created_at: string;
};

export type ChapterSummary = {
  id: string;
  title: string;
  chapter_index: number;
  word_count: number;
  chunk_count: number;
  embedded_count: number;
};

export type ChunkPreview = {
  id: string;
  novel_id: string;
  chapter_id: string;
  chapter_index: number;
  chunk_index: number;
  char_count: number;
  token_count: number;
  has_embedding: boolean;
  text_preview: string;
};

export type ProcessingStatus = {
  novel_id: string;
  chapter_count: number;
  chunk_count: number;
  embedded_count: number;
  missing_embedding_count: number;
  candidate_character_count: number;
  confirmed_character_count: number;
  candidate_alias_count: number;
  candidate_event_count: number;
  candidate_state_change_count: number;
  candidate_state_count: number;
  confirmed_state_count: number;
  prompt_generation_count: number;
};

export type CharacterSummary = {
  id: string;
  novel_id: string;
  canonical_name: string;
  status: string;
  description: string | null;
  source_chunk_ids?: string[];
  confidence: number | null;
  reviewed_by?: string | null;
  review_note?: string | null;
};

export type CharacterStatusFilter = "candidate" | "confirmed" | "rejected" | "all";

export type ChunkNovelResult = {
  novel_id: string;
  chapter_count: number;
  chunk_count: number;
  replaced_existing_chunks: boolean;
};

export type EmbedNovelResult = {
  novel_id: string;
  embedded_count: number;
  remaining_missing_embedding_count: number;
  provider: string;
};

export type ExtractChapterResult = {
  chapter_id: string;
  chapter_index: number;
  event_candidate_count: number;
  state_change_candidate_count: number;
};

export type PromptGeneration = {
  id: string;
  novel_id: string;
  chapter_id: string;
  chapter_index: number;
  character_id: string | null;
  character_state_id: string | null;
  prompt_type: "character" | "scene";
  user_request: string | null;
  final_prompt: string;
  negative_prompt: string | null;
  model_provider: string | null;
  model_name: string | null;
  model_params: Record<string, unknown>;
  used_event_ids: string[];
  used_chunk_ids: string[];
  warnings: Array<Record<string, unknown>>;
  evidence_snapshot: {
    state?: Record<string, unknown> | null;
    events?: Array<Record<string, unknown>>;
    chunks?: Array<Record<string, unknown>>;
  };
};

export type InitialStatePayload = {
  novel_id: string;
  chapter_start: number;
  source_chunk_ids: string[];
  confidence?: number | null;
  fields: {
    appearance?: string | null;
    personality?: string | null;
    identity?: string | null;
    motivation?: string | null;
    relationship_summary?: string | null;
    visual_keywords: string[];
    negative_prompt?: string | null;
  };
};

export type CrawledNovelPreview = {
  novel_md_path: string;
  manifest_path: string;
  title: string;
  chapter_count: number;
  chapters: Array<{
    index: number;
    title: string;
    word_count: number;
    page_urls: string[];
  }>;
  preview_text: string;
  selected_chapter_index: number;
  selected_chapter_title: string;
  chapter_text: string;
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers ?? {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload && typeof payload.detail === "string" ? payload.detail : response.statusText;
    throw new Error(detail);
  }
  return payload as T;
}

export function getNovel(novelId: string): Promise<NovelSummary> {
  return request<NovelSummary>(`/novels/${encodeURIComponent(novelId)}`);
}

export function listChapters(novelId: string): Promise<ChapterSummary[]> {
  return request<ChapterSummary[]>(`/novels/${encodeURIComponent(novelId)}/chapters`);
}

export function listChapterChunks(chapterId: string): Promise<ChunkPreview[]> {
  return request<ChunkPreview[]>(`/chapters/${encodeURIComponent(chapterId)}/chunks`);
}

export function getProcessingStatus(novelId: string): Promise<ProcessingStatus> {
  return request<ProcessingStatus>(`/novels/${encodeURIComponent(novelId)}/processing-status`);
}

export function listCharacters(novelId: string, status: CharacterStatusFilter): Promise<CharacterSummary[]> {
  return request<CharacterSummary[]>(
    `/novels/${encodeURIComponent(novelId)}/characters?status=${encodeURIComponent(status)}`,
  );
}

export function createCharacter(
  novelId: string,
  payload: {
    canonical_name: string;
    description?: string | null;
    status: "candidate" | "confirmed";
    source_chunk_ids?: string[];
    confidence?: number | null;
  },
): Promise<CharacterSummary> {
  return request<CharacterSummary>(`/novels/${encodeURIComponent(novelId)}/characters`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function chunkNovel(
  novelId: string,
  payload?: { target_chars?: number; max_chars?: number },
): Promise<ChunkNovelResult> {
  return request<ChunkNovelResult>(`/novels/${encodeURIComponent(novelId)}/chunk`, {
    method: "POST",
    body: JSON.stringify(payload ?? {}),
  });
}

export function embedNovel(novelId: string, payload?: { batch_size?: number }): Promise<EmbedNovelResult> {
  return request<EmbedNovelResult>(`/novels/${encodeURIComponent(novelId)}/embed`, {
    method: "POST",
    body: JSON.stringify(payload ?? {}),
  });
}

export function extractChapter(chapterId: string): Promise<ExtractChapterResult> {
  return request<ExtractChapterResult>(`/chapters/${encodeURIComponent(chapterId)}/extract`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function listCandidates(novelId: string): Promise<Candidate[]> {
  return request<Candidate[]>(`/review/candidates?novel_id=${encodeURIComponent(novelId)}`);
}

export function listEventCandidates(
  novelId: string,
  filters: { chapter_id?: string; character_id?: string; status?: string } = {},
): Promise<EventCandidate[]> {
  const params = new URLSearchParams({ novel_id: novelId, status: filters.status ?? "candidate" });
  if (filters.chapter_id) params.set("chapter_id", filters.chapter_id);
  if (filters.character_id) params.set("character_id", filters.character_id);
  return request<EventCandidate[]>(`/review/events?${params.toString()}`);
}

export function acceptEventCandidate(id: string, reviewer: string, note?: string): Promise<EventCandidate> {
  return request<EventCandidate>(`/review/events/${encodeURIComponent(id)}/accept`, {
    method: "POST",
    body: JSON.stringify({ reviewer, note: note || null }),
  });
}

export function rejectEventCandidate(id: string, reviewer: string, note?: string): Promise<EventCandidate> {
  return request<EventCandidate>(`/review/events/${encodeURIComponent(id)}/reject`, {
    method: "POST",
    body: JSON.stringify({ reviewer, note: note || null }),
  });
}

export function listStateChangeCandidates(
  novelId: string,
  filters: { chapter_id?: string; character_id?: string; status?: string } = {},
): Promise<StateChangeCandidate[]> {
  const params = new URLSearchParams({ novel_id: novelId, status: filters.status ?? "candidate" });
  if (filters.chapter_id) params.set("chapter_id", filters.chapter_id);
  if (filters.character_id) params.set("character_id", filters.character_id);
  return request<StateChangeCandidate[]>(`/review/state-changes?${params.toString()}`);
}

export function acceptStateChangeCandidate(id: string, reviewer: string, note?: string): Promise<StateChangeCandidate> {
  return request<StateChangeCandidate>(`/review/state-changes/${encodeURIComponent(id)}/accept`, {
    method: "POST",
    body: JSON.stringify({ reviewer, note: note || null }),
  });
}

export function rejectStateChangeCandidate(id: string, reviewer: string, note?: string): Promise<StateChangeCandidate> {
  return request<StateChangeCandidate>(`/review/state-changes/${encodeURIComponent(id)}/reject`, {
    method: "POST",
    body: JSON.stringify({ reviewer, note: note || null }),
  });
}

export function acceptCandidate(targetType: string, id: string, reviewer: string, note?: string): Promise<Candidate> {
  return request<Candidate>(`/review/${targetType}/${id}/accept`, {
    method: "POST",
    body: JSON.stringify({ reviewer, note: note || null }),
  });
}

export function rejectCandidate(targetType: string, id: string, reviewer: string, note?: string): Promise<Candidate> {
  return request<Candidate>(`/review/${targetType}/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ reviewer, note: note || null }),
  });
}

export function confirmAlias(aliasId: string, characterId: string, reviewer: string, note?: string): Promise<Candidate> {
  return request<Candidate>(`/review/aliases/${aliasId}/confirm`, {
    method: "POST",
    body: JSON.stringify({ character_id: characterId, reviewer, note: note || null }),
  });
}

export function listStates(characterId: string): Promise<CharacterState[]> {
  return request<CharacterState[]>(`/characters/${characterId}/states`);
}

export function createInitialState(characterId: string, payload: InitialStatePayload): Promise<CharacterState> {
  return request<CharacterState>(`/characters/${characterId}/initial-state`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function confirmState(stateId: string, reviewer: string, note?: string): Promise<CharacterState> {
  return request<CharacterState>(`/states/${encodeURIComponent(stateId)}/confirm`, {
    method: "POST",
    body: JSON.stringify({ reviewer, note: note || null }),
  });
}

export function generatePrompt(payload: {
  novel_id: string;
  chapter_index: number;
  character_id: string;
  user_request?: string | null;
}): Promise<PromptGeneration> {
  return request<PromptGeneration>("/prompts/generate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listPromptHistory(novelId: string): Promise<PromptGeneration[]> {
  return request<PromptGeneration[]>(`/prompts/history?novel_id=${encodeURIComponent(novelId)}`);
}

export function getPromptDetail(promptId: string): Promise<PromptGeneration> {
  return request<PromptGeneration>(`/prompts/${promptId}`);
}

export function getCrawledNovelPreview(chapterIndex = 1): Promise<CrawledNovelPreview> {
  return request<CrawledNovelPreview>(`/operator/crawled-novel-preview?chapter_index=${encodeURIComponent(chapterIndex)}`);
}
