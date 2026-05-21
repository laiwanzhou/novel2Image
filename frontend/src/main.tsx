import { useState } from "react";
import { createRoot } from "react-dom/client";
import { CandidateReviewPage } from "./pages/CandidateReviewPage";
import { CharacterStatesPage } from "./pages/CharacterStatesPage";
import { NovelWorkspacePage } from "./pages/NovelWorkspacePage";
import { PromptHistoryPage } from "./pages/PromptHistoryPage";
import "./styles.css";

type Tab = "workspace" | "review" | "states" | "prompts";

function App() {
  const [tab, setTab] = useState<Tab>("workspace");

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>小说角色视觉化管理台</h1>
          <p>审核候选知识、查看角色状态版本，并追踪 prompt 证据链。</p>
        </div>
        <nav className="tabs" aria-label="Admin sections">
          <button className={tab === "workspace" ? "active" : ""} onClick={() => setTab("workspace")}>
            工作台
          </button>
          <button className={tab === "review" ? "active" : ""} onClick={() => setTab("review")}>
            审核
          </button>
          <button className={tab === "states" ? "active" : ""} onClick={() => setTab("states")}>
            角色状态
          </button>
          <button className={tab === "prompts" ? "active" : ""} onClick={() => setTab("prompts")}>
            Prompt 记录
          </button>
        </nav>
      </header>
      {tab === "workspace" && <NovelWorkspacePage />}
      {tab === "review" && <CandidateReviewPage />}
      {tab === "states" && <CharacterStatesPage />}
      {tab === "prompts" && <PromptHistoryPage />}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
