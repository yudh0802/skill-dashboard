#!/usr/bin/env python3
"""
gen_skill_data.py — Extract Claude Code skill usage data and output data.json.

Data sources:
  1. ~/.claude/history.jsonl       (slash commands)
  2. ~/.claude/logs/skill-usage.jsonl (direct skill invocations)
  3. ~/.claude/projects/**/*.jsonl  (Skill tool calls in sessions)

Merge strategy: max(source1, source2, source3) per unique skill.

Usage:
  python3 gen_skill_data.py            # default 30 days
  python3 gen_skill_data.py --days 60  # custom window
"""

import argparse
import json
import os
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HOME = Path.home()
HISTORY_FILE = HOME / ".claude" / "history.jsonl"
SKILL_USAGE_FILE = HOME / ".claude" / "logs" / "skill-usage.jsonl"
PROJECTS_DIR = HOME / ".claude" / "projects"
CUSTOM_SKILLS_DIR = HOME / ".claude" / "skills"
OUTPUT_FILE = Path(__file__).parent / "data.json"

BUILTIN_COMMANDS = {
    "help", "clear", "compact", "exit", "quit", "status", "fast", "model",
    "memory", "init", "cost", "config", "permissions", "login", "logout",
    "doctor", "review", "bug", "terminal-setup", "vim", "allowed-tools",
    "mcp", "ide", "add-dir", "pr", "hooks", "listen", "resume", "rename",
    "plugin", "effort",
}

# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------

CATEGORIES = {
    "session-wrap:wrap": "workflow",
    "session-wrap:session-wrap": "workflow",
    "session-wrap:history-insight": "workflow",
    "session-wrap:session-analyzer": "workflow",
    "meeting": "productivity",
    "google-calendar:google-calendar": "productivity",
    "morning-briefing": "productivity",
    "prd": "productivity",
    "challenge": "productivity",
    "stt": "productivity",
    "clarify:vague": "productivity",
    "clarify:unknown": "productivity",
    "clarify:metamedium": "productivity",
    "context": "knowledge",
    "memo": "knowledge",
    "notion-reader": "knowledge",
    "research": "knowledge",
    "wiki-ingest": "knowledge",
    "wiki-lint": "knowledge",
    "crig-concept-learning": "knowledge",
    "professor-research": "knowledge",
    "video-dl": "media",
    "audio-transcribe": "media",
    "pptx-design-styles": "design",
    "frontend-design:frontend-design": "design",
    "frontend-design": "design",
    "superpowers:brainstorming": "superpowers",
    "superpowers:systematic-debugging": "superpowers",
    "superpowers:writing-plans": "superpowers",
    "superpowers:writing-skills": "superpowers",
    "superpowers:using-git-worktrees": "superpowers",
    "superpowers:subagent-driven-development": "superpowers",
    "superpowers:test-driven-development": "superpowers",
    "superpowers:executing-plans": "superpowers",
    "superpowers:using-superpowers": "superpowers",
    "superpowers:dispatching-parallel-agents": "superpowers",
    "superpowers:finishing-a-development-branch": "superpowers",
    "superpowers:receiving-code-review": "superpowers",
    "superpowers:requesting-code-review": "superpowers",
    "superpowers:verification-before-completion": "superpowers",
    "oh-my-claudecode:cancel": "omc",
    "oh-my-claudecode:omc-teams": "omc",
    "oh-my-claudecode:autopilot": "omc",
    "oh-my-claudecode:omc-help": "omc",
    "oh-my-claudecode:ralph": "omc",
    "oh-my-claudecode:ultrawork": "omc",
    "oh-my-claudecode:ultraqa": "omc",
    "oh-my-claudecode:team": "omc",
    "oh-my-claudecode:ccg": "omc",
    "oh-my-claudecode:omc-setup": "omc",
    "oh-my-claudecode:mcp-setup": "omc",
    "oh-my-claudecode:hud": "omc",
    "oh-my-claudecode:trace": "omc",
    "oh-my-claudecode:debug": "omc",
    "oh-my-claudecode:deepinit": "omc",
    "oh-my-claudecode:release": "omc",
    "oh-my-claudecode:sciomc": "omc",
    "oh-my-claudecode:ralplan": "omc",
    "oh-my-claudecode:deep-dive": "omc",
    "oh-my-claudecode:deep-interview": "omc",
    "oh-my-claudecode:external-context": "omc",
    "oh-my-claudecode:verify": "omc",
    "oh-my-claudecode:configure-notifications": "omc",
    "oh-my-claudecode:ask": "omc",
    "oh-my-claudecode:skill": "omc",
    "oh-my-claudecode:learner": "omc",
    "oh-my-claudecode:omc-doctor": "omc",
    "oh-my-claudecode:remember": "omc",
    "oh-my-claudecode:plan": "omc",
    "oh-my-claudecode:self-improve": "omc",
    "oh-my-claudecode:project-session-manager": "omc",
    "oh-my-claudecode:wiki": "omc",
    "oh-my-claudecode:visual-verdict": "omc",
    "oh-my-claudecode:ai-slop-cleaner": "omc",
    "oh-my-claudecode:skillify": "omc",
    "oh-my-claudecode:writer-memory": "omc",
    "oh-my-claudecode:setup": "omc",
    "update-config": "config",
    "keybindings-help": "config",
    "kakaotalk:kakaotalk": "communication",
    "kakaotalk": "communication",
    "coach-changjun": "coaching",
    "product-psychology-for-vibe-coding": "pm",
    "pdf-to-excel": "utility",
    "visualize-notion": "utility",
    "my-tools": "utility",
    "simplify": "utility",
    "loop": "utility",
    "schedule": "utility",
    "claude-api": "dev",
    "interactive-review:review": "workflow",
    "hook-skip-pattern": "config",
    "notion-extract": "knowledge",
    "defuddle": "knowledge",
}

CATEGORY_COLORS = {
    "knowledge": "#5E6AD2",
    "workflow": "#E5793A",
    "productivity": "#4EA87E",
    "superpowers": "#D95F8C",
    "media": "#C084FC",
    "omc": "#6B7280",
    "config": "#F59E0B",
    "design": "#EC4899",
    "communication": "#06B6D4",
    "coaching": "#8B5CF6",
    "pm": "#F97316",
    "utility": "#9CA0A8",
    "dev": "#10B981",
    "other": "#9CA0A8",
}

CATEGORY_LABELS = {
    "knowledge": "Knowledge",
    "workflow": "Workflow",
    "productivity": "Productivity",
    "superpowers": "Superpowers",
    "media": "Media",
    "omc": "OMC",
    "config": "Config",
    "design": "Design",
    "communication": "Communication",
    "coaching": "Coaching",
    "pm": "PM",
    "utility": "Utility",
    "dev": "Dev",
    "other": "Other",
}

# ---------------------------------------------------------------------------
# Skill registry — all 89 skills with metadata
# ---------------------------------------------------------------------------

SKILL_REGISTRY = {
    # ── Knowledge ──
    "context": {
        "description": "Load full project context from all knowledge sources",
        "description_long": "Searches Obsidian vault, Notion workspaces, project memory, and session history to assemble comprehensive context before starting work. Essential for complex tasks requiring cross-source understanding.",
        "source": "custom",
        "triggers": ["/context", "컨텍스트 로드", "프로젝트 배경"],
        "capabilities": ["obsidian-search", "notion-search", "memory-read", "session-history"],
        "related": ["research", "memo", "wiki-ingest"],
    },
    "memo": {
        "description": "Quick memo capture to Obsidian Knowledge Vault",
        "description_long": "Captures quick memos to Obsidian daily notes or inbox. Handles wikilinks, tags, and automatic daily note creation. The most frequently used knowledge capture tool.",
        "source": "custom",
        "triggers": ["/memo", "메모", "기록해줘", "노트해줘"],
        "capabilities": ["obsidian-write", "daily-note", "wikilink", "tagging"],
        "related": ["context", "research", "wiki-ingest"],
    },
    "notion-reader": {
        "description": "Read public Notion pages as markdown",
        "description_long": "Extracts content from public Notion pages using the unofficial API with cursor-based pagination. Converts blocks to clean markdown. Useful for consuming shared documentation and resources.",
        "source": "custom",
        "triggers": ["/notion-reader", "노션 페이지 읽어줘", "notion.site URL"],
        "capabilities": ["notion-api", "markdown-extract", "pagination"],
        "related": ["notion-extract", "visualize-notion", "context"],
    },
    "research": {
        "description": "Search across all knowledge sources for context on a topic",
        "description_long": "Multi-source research across Obsidian, Notion, web, and memory. Synthesizes findings into structured output with citations.",
        "source": "custom",
        "triggers": ["/research", "조사해줘", "리서치", "찾아줘"],
        "capabilities": ["multi-source-search", "synthesis", "citation"],
        "related": ["context", "memo", "wiki-ingest"],
    },
    "wiki-ingest": {
        "description": "Ingest materials into LLM Wiki",
        "description_long": "Reads source material (lecture notes, articles, meeting notes, PDFs) and integrates key information into the LLM Wiki knowledge base. Updates index and log files.",
        "source": "custom",
        "triggers": ["/wiki-ingest", "위키에 정리해줘", "인제스트", "위키 업데이트"],
        "capabilities": ["wiki-write", "index-update", "conflict-detection"],
        "related": ["wiki-lint", "context", "memo"],
    },
    "wiki-lint": {
        "description": "Audit wiki health: conflicts, stale pages, gaps",
        "description_long": "Checks the LLM Wiki for contradictions, outdated information, orphan pages, missing concepts, and data gaps. Produces actionable fix suggestions.",
        "source": "custom",
        "triggers": ["/wiki-lint", "위키 점검", "위키 린트", "wiki lint"],
        "capabilities": ["conflict-scan", "staleness-check", "orphan-detect", "gap-analysis"],
        "related": ["wiki-ingest", "context"],
    },
    "crig-concept-learning": {
        "description": "Deep concept understanding via rigging and crystallization",
        "description_long": "Scaffolds understanding of complex concepts by breaking them into structural components (rigging) and distilling into a seed sentence. Ideal for learning new domains.",
        "source": "custom",
        "triggers": ["이해하고 싶어", "그려지지 않아", "핵심이 뭐야?", "정리해봐"],
        "capabilities": ["concept-rigging", "seed-sentence", "structural-analysis"],
        "related": ["research", "context"],
    },
    "professor-research": {
        "description": "Research professor/researcher profiles from multiple sources",
        "description_long": "Investigates professor/researcher profiles using email OSINT, academic databases (DBpia, Scholar, ResearchGate), university faculty pages, and Yes24 author pages.",
        "source": "custom",
        "triggers": ["/professor-research", "교수 정보 찾아줘", "프로필 조사"],
        "capabilities": ["osint", "academic-db-search", "profile-synthesis"],
        "related": ["research", "context"],
    },
    "notion-extract": {
        "description": "Safe Notion workspace search with field extraction within context limits",
        "description_long": "Searches Notion workspaces and extracts only core fields to stay within context limits. Safer than raw MCP calls for large databases.",
        "source": "plugin:notion-extract",
        "triggers": ["노션 검색", "notion extract"],
        "capabilities": ["notion-search", "field-extract", "context-safe"],
        "related": ["notion-reader", "context"],
    },
    "defuddle": {
        "description": "Extract clean readable content from web pages",
        "description_long": "Strips clutter from web pages and extracts the main readable content as clean markdown. Useful for articles, blog posts, and documentation.",
        "source": "plugin:defuddle",
        "triggers": ["웹 페이지 읽어줘", "URL 내용 추출"],
        "capabilities": ["web-extract", "readability", "markdown-convert"],
        "related": ["notion-reader", "research"],
    },
    # ── Workflow ──
    "session-wrap:wrap": {
        "description": "Session wrap-up — analyze, suggest docs, automation, follow-ups",
        "description_long": "Analyzes the current session to suggest documentation updates, automation opportunities, and follow-up tasks. The primary session-end workflow.",
        "source": "plugin:session-wrap",
        "triggers": ["/wrap", "/session-wrap:wrap", "세션 정리"],
        "capabilities": ["session-analysis", "doc-suggestions", "follow-up-generation"],
        "related": ["session-wrap:session-wrap", "session-wrap:history-insight"],
    },
    "session-wrap:session-wrap": {
        "description": "Full session wrap — document learnings, commit suggestions",
        "description_long": "Comprehensive session wrap-up that documents learnings, suggests commits, and captures reusable patterns from the current coding session.",
        "source": "plugin:session-wrap",
        "triggers": ["/session-wrap:session-wrap", "wrap up session", "end session"],
        "capabilities": ["session-analysis", "commit-suggestions", "learning-capture"],
        "related": ["session-wrap:wrap", "session-wrap:history-insight"],
    },
    "session-wrap:history-insight": {
        "description": "Capture and reference session history for saving or analysis",
        "description_long": "Access, capture, or reference Claude Code session history. Useful for saving important exchanges, extracting patterns, or auditing past sessions.",
        "source": "plugin:session-wrap",
        "triggers": ["/session-wrap:history-insight", "capture session", "save session history"],
        "capabilities": ["history-access", "pattern-extract", "session-audit"],
        "related": ["session-wrap:wrap", "session-wrap:session-wrap"],
    },
    "session-wrap:session-analyzer": {
        "description": "Analyze and verify skill execution in past sessions",
        "description_long": "Evaluates skill execution correctness by analyzing session logs. Verifies that skills ran as expected and surfaces any anomalies.",
        "source": "plugin:session-wrap",
        "triggers": ["analyze session", "세션 분석", "스킬 실행 검증"],
        "capabilities": ["log-analysis", "execution-verify", "anomaly-detect"],
        "related": ["session-wrap:wrap"],
    },
    "interactive-review:review": {
        "description": "Interactive markdown review with web UI",
        "description_long": "Opens a web-based review interface for markdown documents. Supports inline comments and structured feedback.",
        "source": "plugin:interactive-review",
        "triggers": ["review this", "검토해줘", "피드백"],
        "capabilities": ["web-ui", "inline-comments", "structured-feedback"],
        "related": ["simplify"],
    },
    # ── Productivity ──
    "meeting": {
        "description": "Tiro meeting notes from Notion to Obsidian",
        "description_long": "Reads Tiro-transcribed meeting notes from Notion, corrects STT errors using glossary, structures the content, collects related note context, and saves to Obsidian.",
        "source": "custom",
        "triggers": ["/meeting", "미팅노트 정리해줘", "회의록"],
        "capabilities": ["notion-read", "stt-correction", "obsidian-write", "context-gather"],
        "related": ["stt", "context", "memo"],
    },
    "google-calendar:google-calendar": {
        "description": "Google Calendar events CRUD",
        "description_long": "Create, read, update, and delete Google Calendar events. Supports the personal account with Asia/Seoul timezone.",
        "source": "plugin:google-calendar",
        "triggers": ["/google-calendar", "일정 추가", "캘린더", "스케줄"],
        "capabilities": ["event-create", "event-read", "event-update", "event-delete"],
        "related": ["morning-briefing", "schedule"],
    },
    "morning-briefing": {
        "description": "Morning briefing from calendar, memory, and recent activity",
        "description_long": "Generates a comprehensive morning briefing by pulling today's calendar events, recent memory entries, pending tasks, and session activity summary.",
        "source": "custom",
        "triggers": ["/morning-briefing", "오늘 일정", "모닝 브리핑"],
        "capabilities": ["calendar-read", "memory-read", "task-summary", "activity-digest"],
        "related": ["google-calendar:google-calendar", "context"],
    },
    "prd": {
        "description": "Socratic questioning-based PRD writing workflow",
        "description_long": "Guides PRD creation through Socratic questioning: asks 5-7 clarifying questions with rationale, gathers answers, challenges with 2-3 follow-ups, then drafts the PRD.",
        "source": "custom",
        "triggers": ["/prd", "PRD 작성", "기획서"],
        "capabilities": ["socratic-questioning", "prd-generation", "multi-perspective-review"],
        "related": ["challenge", "product-psychology-for-vibe-coding"],
    },
    "challenge": {
        "description": "Devil's Advocate analysis for decisions and strategies",
        "description_long": "Critically analyzes strategies, plans, and decisions by identifying dangerous assumptions, failure scenarios, and overlooked perspectives.",
        "source": "custom",
        "triggers": ["/challenge", "도전해봐", "반박해줘", "위험 분석"],
        "capabilities": ["assumption-challenge", "failure-scenario", "blind-spot-detection"],
        "related": ["prd", "clarify:unknown"],
    },
    "stt": {
        "description": "Correct and structure STT transcripts",
        "description_long": "Corrects speech-to-text transcription errors using glossary-based matching and structures the output into readable format.",
        "source": "custom",
        "triggers": ["/stt", "STT 교정", "음성 텍스트 교정"],
        "capabilities": ["stt-correction", "glossary-match", "text-structure"],
        "related": ["audio-transcribe", "meeting"],
    },
    "clarify:vague": {
        "description": "Iterative questioning to clarify ambiguous requirements",
        "description_long": "When requirements are ambiguous, uses iterative questioning to make them actionable. Refines until the requirement is implementable.",
        "source": "plugin:clarify",
        "triggers": ["clarify requirements", "요구사항 명확히", "요구사항 정리"],
        "capabilities": ["iterative-questioning", "requirement-refinement"],
        "related": ["clarify:unknown", "clarify:metamedium", "prd"],
    },
    "clarify:unknown": {
        "description": "Surface hidden assumptions with Known/Unknown 4-quadrant framework",
        "description_long": "Applies the Known/Unknown 4-quadrant framework to surface blind spots and hidden assumptions in strategies, plans, or decisions.",
        "source": "plugin:clarify",
        "triggers": ["known unknown", "4분면 분석", "blind spots"],
        "capabilities": ["quadrant-analysis", "assumption-surface", "blind-spot-detect"],
        "related": ["clarify:vague", "challenge"],
    },
    "clarify:metamedium": {
        "description": "Content vs form analysis — optimize what vs change how",
        "description_long": "Helps decide whether to optimize content (what) or change the form/medium (how). Useful when stuck between improving existing approach vs trying a new format.",
        "source": "plugin:clarify",
        "triggers": ["내용 vs 형식", "content vs form", "metamedium"],
        "capabilities": ["content-form-analysis", "medium-evaluation"],
        "related": ["clarify:vague", "superpowers:brainstorming"],
    },
    # ── Media ──
    "video-dl": {
        "description": "Download videos from Instagram, YouTube, TikTok, X and more",
        "description_long": "Downloads videos and images from nearly any platform using yt-dlp with browser cookie authentication. Supports audio-only extraction and custom output paths.",
        "source": "custom",
        "triggers": ["/video-dl", "영상 다운로드", "동영상 저장", "릴스 받아줘"],
        "capabilities": ["video-download", "audio-extract", "multi-platform", "cookie-auth"],
        "related": ["audio-transcribe"],
    },
    "audio-transcribe": {
        "description": "Local audio transcription with mlx_whisper + glossary correction",
        "description_long": "Transcribes m4a/mp3/wav/mp4 audio files locally using mlx_whisper. Automatically applies glossary-based correction and removes Whisper hallucinations.",
        "source": "custom",
        "triggers": ["/audio-transcribe", "오디오 전사", "녹음 텍스트로"],
        "capabilities": ["local-transcription", "glossary-correction", "hallucination-removal"],
        "related": ["video-dl", "stt", "meeting"],
    },
    # ── Design ──
    "pptx-design-styles": {
        "description": "PPTX slides with 30 modern design styles",
        "description_long": "Creates professional PPTX presentations using 30 modern design styles including Glassmorphism, Neo-Brutalism, Bento Grid, Dark Academia, and more.",
        "source": "custom",
        "triggers": ["/pptx-design-styles", "슬라이드 만들어줘", "발표자료"],
        "capabilities": ["pptx-generation", "30-design-styles", "modern-layout"],
        "related": ["frontend-design:frontend-design"],
    },
    "frontend-design:frontend-design": {
        "description": "Production-grade frontend interfaces with high design quality",
        "description_long": "Creates distinctive, production-grade frontend interfaces that avoid generic AI aesthetics. Generates creative, polished code for web components, pages, and applications.",
        "source": "plugin:frontend-design",
        "triggers": ["/frontend-design", "프론트엔드 만들어줘", "웹 UI 디자인"],
        "capabilities": ["html-css-js", "responsive-design", "creative-layout", "production-grade"],
        "related": ["pptx-design-styles", "product-psychology-for-vibe-coding"],
    },
    "frontend-design": {
        "description": "Production-grade frontend interfaces (shorthand)",
        "description_long": "Shorthand alias for frontend-design:frontend-design.",
        "source": "plugin:frontend-design",
        "triggers": ["/frontend-design"],
        "capabilities": ["html-css-js", "responsive-design"],
        "related": ["frontend-design:frontend-design"],
    },
    # ── Superpowers ──
    "superpowers:brainstorming": {
        "description": "Explore intent, requirements and design before implementation",
        "description_long": "Must-use skill before any creative work. Explores user intent, gathers requirements, and designs the approach before touching code. Prevents premature implementation.",
        "source": "plugin:superpowers",
        "triggers": ["creative work", "new feature", "build component"],
        "capabilities": ["intent-exploration", "requirement-gather", "design-first"],
        "related": ["superpowers:writing-plans", "superpowers:subagent-driven-development"],
    },
    "superpowers:systematic-debugging": {
        "description": "Root-cause analysis before proposing fixes",
        "description_long": "Systematic debugging approach: reproduce, isolate, hypothesize, verify. Prevents shotgun debugging by requiring evidence-based diagnosis.",
        "source": "plugin:superpowers",
        "triggers": ["bug", "test failure", "unexpected behavior"],
        "capabilities": ["reproduction", "isolation", "hypothesis-testing", "root-cause"],
        "related": ["superpowers:test-driven-development", "superpowers:verification-before-completion"],
    },
    "superpowers:writing-plans": {
        "description": "Create implementation plans before touching code",
        "description_long": "Structures multi-step tasks into detailed implementation plans with clear phases, dependencies, and checkpoints.",
        "source": "plugin:superpowers",
        "triggers": ["plan this", "implementation plan", "multi-step task"],
        "capabilities": ["task-decomposition", "dependency-mapping", "checkpoint-design"],
        "related": ["superpowers:executing-plans", "superpowers:brainstorming"],
    },
    "superpowers:writing-skills": {
        "description": "Create or edit skills with deployment verification",
        "description_long": "Guides creation and editing of Claude Code skills with proper structure, testing, and deployment verification.",
        "source": "plugin:superpowers",
        "triggers": ["create skill", "edit skill", "new skill"],
        "capabilities": ["skill-scaffold", "skill-test", "deployment-verify"],
        "related": ["oh-my-claudecode:skillify", "oh-my-claudecode:skill"],
    },
    "superpowers:using-git-worktrees": {
        "description": "Create isolated git worktrees for feature work",
        "description_long": "Creates isolated git worktrees with smart directory selection and safety verification. Ideal for starting feature work that needs isolation.",
        "source": "plugin:superpowers",
        "triggers": ["worktree", "isolated branch", "feature isolation"],
        "capabilities": ["worktree-create", "directory-select", "safety-verify"],
        "related": ["superpowers:finishing-a-development-branch"],
    },
    "superpowers:subagent-driven-development": {
        "description": "Execute plans with independent parallel sub-agents",
        "description_long": "Dispatches independent implementation tasks to parallel sub-agents within the current session. Maximizes throughput for non-dependent work.",
        "source": "plugin:superpowers",
        "triggers": ["parallel tasks", "independent implementation"],
        "capabilities": ["parallel-dispatch", "task-independence-check", "result-merge"],
        "related": ["superpowers:dispatching-parallel-agents", "superpowers:writing-plans"],
    },
    "superpowers:test-driven-development": {
        "description": "Write tests before implementation code",
        "description_long": "Enforces TDD: red (write failing test) -> green (minimal implementation) -> refactor. Ensures test coverage drives development.",
        "source": "plugin:superpowers",
        "triggers": ["tdd", "test first", "red green"],
        "capabilities": ["test-first", "red-green-refactor", "coverage-driven"],
        "related": ["superpowers:systematic-debugging", "superpowers:verification-before-completion"],
    },
    "superpowers:executing-plans": {
        "description": "Execute implementation plans with review checkpoints",
        "description_long": "Executes written implementation plans in a separate session with built-in review checkpoints at each phase.",
        "source": "plugin:superpowers",
        "triggers": ["execute plan", "run the plan"],
        "capabilities": ["plan-execution", "checkpoint-review", "phase-tracking"],
        "related": ["superpowers:writing-plans", "superpowers:subagent-driven-development"],
    },
    "superpowers:using-superpowers": {
        "description": "Establish how to find and use skills at conversation start",
        "description_long": "Entry point skill that teaches how to discover and invoke other skills. Must be invoked before any response including clarifying questions.",
        "source": "plugin:superpowers",
        "triggers": ["start conversation", "skill discovery"],
        "capabilities": ["skill-discovery", "skill-routing"],
        "related": ["my-tools"],
    },
    "superpowers:dispatching-parallel-agents": {
        "description": "Dispatch 2+ independent tasks to parallel agents",
        "description_long": "When facing multiple independent tasks without shared state, dispatches them to parallel agents for concurrent execution.",
        "source": "plugin:superpowers",
        "triggers": ["parallel agents", "concurrent tasks"],
        "capabilities": ["agent-dispatch", "independence-verify", "result-collect"],
        "related": ["superpowers:subagent-driven-development"],
    },
    "superpowers:finishing-a-development-branch": {
        "description": "Guide completion of development branch — merge, PR, or cleanup",
        "description_long": "When implementation is complete and tests pass, presents structured options for integrating work: merge, PR creation, or cleanup.",
        "source": "plugin:superpowers",
        "triggers": ["branch done", "ready to merge", "finish feature"],
        "capabilities": ["merge-guide", "pr-create", "branch-cleanup"],
        "related": ["superpowers:using-git-worktrees", "superpowers:requesting-code-review"],
    },
    "superpowers:receiving-code-review": {
        "description": "Handle code review feedback with technical rigor",
        "description_long": "Processes code review feedback with verification, not blind agreement. Requires technical rigor before implementing suggestions.",
        "source": "plugin:superpowers",
        "triggers": ["review feedback", "code review comments"],
        "capabilities": ["feedback-analysis", "technical-verify", "selective-implement"],
        "related": ["superpowers:requesting-code-review"],
    },
    "superpowers:requesting-code-review": {
        "description": "Request code review to verify work meets requirements",
        "description_long": "Triggers code review when completing tasks or before merging. Verifies work meets stated requirements.",
        "source": "plugin:superpowers",
        "triggers": ["request review", "before merge"],
        "capabilities": ["review-request", "requirement-verify"],
        "related": ["superpowers:receiving-code-review", "superpowers:verification-before-completion"],
    },
    "superpowers:verification-before-completion": {
        "description": "Verify work before claiming completion — evidence first",
        "description_long": "Must run verification commands and confirm output before making any success claims. Evidence before assertions, always.",
        "source": "plugin:superpowers",
        "triggers": ["about to commit", "claiming done", "before PR"],
        "capabilities": ["verification-run", "evidence-collect", "assertion-gate"],
        "related": ["oh-my-claudecode:verify", "superpowers:requesting-code-review"],
    },
    # ── OMC ──
    "oh-my-claudecode:cancel": {
        "description": "Cancel any active OMC execution mode",
        "description_long": "Cancels autopilot, ralph, ultrawork, ultraqa, swarm, ultrapilot, pipeline, or team modes. Use --force to clear all state.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/cancel", "stop", "중단"],
        "capabilities": ["mode-cancel", "state-clear"],
        "related": [],
    },
    "oh-my-claudecode:omc-teams": {
        "description": "CLI-team runtime for claude/codex/gemini workers in tmux",
        "description_long": "Spawns CLI workers (Claude, Codex, or Gemini) in tmux panes for process-based parallel execution.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/omc-teams", "codex", "gemini workers"],
        "capabilities": ["tmux-spawn", "multi-model", "parallel-cli"],
        "related": ["oh-my-claudecode:ccg", "oh-my-claudecode:team"],
    },
    "oh-my-claudecode:autopilot": {
        "description": "Full autonomous execution from idea to working code",
        "description_long": "End-to-end autonomous execution: plan, implement, test, verify. Takes an idea and delivers working code.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/autopilot", "autopilot", "build me"],
        "capabilities": ["plan", "implement", "test", "verify", "autonomous"],
        "related": ["oh-my-claudecode:ralph", "oh-my-claudecode:ultrawork"],
    },
    "oh-my-claudecode:omc-help": {
        "description": "Show OMC help and available commands",
        "description_long": "Displays available OMC commands, agents, tools, and skills with usage examples.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/omc-help", "omc help"],
        "capabilities": ["help-display", "command-list"],
        "related": ["my-tools"],
    },
    "oh-my-claudecode:ralph": {
        "description": "Self-referential loop until task completion with verification",
        "description_long": "Keeps working in a loop until the task is fully completed and verified. Includes ultrawork for maximum parallelism.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/ralph", "ralph", "don't stop", "must complete"],
        "capabilities": ["self-loop", "verification", "persistence"],
        "related": ["oh-my-claudecode:autopilot", "oh-my-claudecode:ultrawork"],
    },
    "oh-my-claudecode:ultrawork": {
        "description": "Maximum parallelism with parallel agent orchestration",
        "description_long": "Parallel execution engine for high-throughput task completion. Dispatches work to multiple agents simultaneously.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/ultrawork", "ulw", "ultrawork"],
        "capabilities": ["parallel-agents", "high-throughput", "orchestration"],
        "related": ["oh-my-claudecode:ralph", "oh-my-claudecode:autopilot"],
    },
    "oh-my-claudecode:ultraqa": {
        "description": "QA cycling — test, verify, fix, repeat until goal met",
        "description_long": "Iterative QA workflow that runs tests, verifies results, fixes issues, and repeats until the quality goal is met.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/ultraqa", "qa cycle"],
        "capabilities": ["test-cycle", "auto-fix", "goal-verify"],
        "related": ["oh-my-claudecode:verify"],
    },
    "oh-my-claudecode:team": {
        "description": "N coordinated agents on shared task list",
        "description_long": "Orchestrates N coordinated Claude Code agents working on a shared task list with stage-aware routing through plan, PRD, exec, verify, and fix stages.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/team", "team", "coordinated team"],
        "capabilities": ["multi-agent", "task-list", "stage-routing"],
        "related": ["oh-my-claudecode:omc-teams", "oh-my-claudecode:ralph"],
    },
    "oh-my-claudecode:ccg": {
        "description": "Claude-Codex-Gemini tri-model orchestration",
        "description_long": "Fans out work to Codex and Gemini via /ask, then Claude synthesizes the results for tri-model consensus.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/ccg", "tri-model", "claude codex gemini"],
        "capabilities": ["tri-model", "fan-out", "synthesis"],
        "related": ["oh-my-claudecode:omc-teams"],
    },
    "oh-my-claudecode:omc-setup": {
        "description": "Install or refresh oh-my-claudecode",
        "description_long": "Canonical setup flow for oh-my-claudecode plugin, npm, and local-dev installations.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/omc-setup", "setup omc"],
        "capabilities": ["install", "refresh", "configure"],
        "related": ["oh-my-claudecode:omc-doctor", "oh-my-claudecode:setup"],
    },
    "oh-my-claudecode:mcp-setup": {
        "description": "Configure popular MCP servers",
        "description_long": "Sets up MCP (Model Context Protocol) servers for enhanced agent capabilities.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/mcp-setup", "setup mcp"],
        "capabilities": ["mcp-configure", "server-setup"],
        "related": ["oh-my-claudecode:omc-setup"],
    },
    "oh-my-claudecode:hud": {
        "description": "Configure HUD display options",
        "description_long": "Configures heads-up display layout, presets, and display elements for the OMC interface.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/hud", "hud config"],
        "capabilities": ["hud-layout", "preset-select", "display-config"],
        "related": [],
    },
    "oh-my-claudecode:trace": {
        "description": "Evidence-driven tracing with competing hypotheses",
        "description_long": "Orchestrates competing tracer hypotheses in team mode for evidence-driven investigation of complex issues.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/trace", "trace this"],
        "capabilities": ["hypothesis-compete", "evidence-driven", "team-trace"],
        "related": ["oh-my-claudecode:debug", "superpowers:systematic-debugging"],
    },
    "oh-my-claudecode:debug": {
        "description": "Diagnose OMC session or repo state",
        "description_long": "Diagnoses the current OMC session or repository state using logs, traces, state inspection, and focused reproduction.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/debug", "omc debug"],
        "capabilities": ["log-inspect", "state-diagnose", "reproduction"],
        "related": ["oh-my-claudecode:trace", "oh-my-claudecode:omc-doctor"],
    },
    "oh-my-claudecode:deepinit": {
        "description": "Deep codebase init with hierarchical AGENTS.md",
        "description_long": "Performs deep codebase initialization by generating hierarchical AGENTS.md documentation for the project.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/deepinit", "deepinit"],
        "capabilities": ["codebase-scan", "agents-md-generate", "hierarchy-map"],
        "related": ["oh-my-claudecode:omc-setup"],
    },
    "oh-my-claudecode:release": {
        "description": "Automated release workflow for oh-my-claudecode",
        "description_long": "Handles the release process for oh-my-claudecode including versioning, changelog, and publishing.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/release"],
        "capabilities": ["version-bump", "changelog", "publish"],
        "related": [],
    },
    "oh-my-claudecode:sciomc": {
        "description": "Parallel scientist agents for comprehensive analysis",
        "description_long": "Orchestrates parallel scientist agents in AUTO mode for comprehensive data and statistical analysis.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/sciomc", "parallel analysis"],
        "capabilities": ["parallel-science", "statistical-analysis", "auto-mode"],
        "related": ["oh-my-claudecode:ultrawork"],
    },
    "oh-my-claudecode:ralplan": {
        "description": "Consensus planning with Planner, Architect, Critic iteration",
        "description_long": "Iterative planning with Planner, Architect, and Critic agents until consensus. Supports --deliberate for high-risk work with pre-mortem and expanded test planning.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/ralplan", "consensus plan"],
        "capabilities": ["consensus-plan", "multi-agent-review", "deliberation"],
        "related": ["oh-my-claudecode:plan"],
    },
    "oh-my-claudecode:deep-dive": {
        "description": "Trace + deep-interview pipeline with 3-point injection",
        "description_long": "2-stage pipeline: causal investigation (trace) followed by requirements crystallization (deep-interview) with 3-point injection.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/deep-dive"],
        "capabilities": ["causal-trace", "requirements-crystallize", "3-point-inject"],
        "related": ["oh-my-claudecode:trace", "oh-my-claudecode:deep-interview"],
    },
    "oh-my-claudecode:deep-interview": {
        "description": "Socratic deep interview with ambiguity gating",
        "description_long": "Socratic deep interview with mathematical ambiguity gating before autonomous execution. Ensures requirements are crystal clear.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/deep-interview"],
        "capabilities": ["socratic-interview", "ambiguity-gate", "pre-execution"],
        "related": ["oh-my-claudecode:deep-dive", "clarify:vague"],
    },
    "oh-my-claudecode:external-context": {
        "description": "Parallel document-specialist agents for web searches",
        "description_long": "Invokes parallel document-specialist agents to perform external web searches and documentation lookup.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/external-context", "web search"],
        "capabilities": ["parallel-search", "doc-lookup", "web-research"],
        "related": ["research", "context"],
    },
    "oh-my-claudecode:verify": {
        "description": "Verify changes really work before claiming completion",
        "description_long": "Runs verification checks to confirm that changes actually work before claiming completion. Evidence-based completion gate.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/verify", "verify this"],
        "capabilities": ["run-verify", "evidence-gate", "completion-check"],
        "related": ["superpowers:verification-before-completion"],
    },
    "oh-my-claudecode:configure-notifications": {
        "description": "Configure Telegram, Discord, or Slack notifications",
        "description_long": "Sets up notification integrations via natural language for Telegram, Discord, or Slack.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["configure discord", "setup telegram", "configure slack"],
        "capabilities": ["telegram", "discord", "slack", "notification-config"],
        "related": [],
    },
    "oh-my-claudecode:ask": {
        "description": "Process-first advisor routing for Claude, Codex, or Gemini",
        "description_long": "Routes questions to Claude, Codex, or Gemini via /ask with artifact capture. No raw CLI assembly needed.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/ask", "ask codex", "ask gemini"],
        "capabilities": ["model-routing", "artifact-capture"],
        "related": ["oh-my-claudecode:ccg"],
    },
    "oh-my-claudecode:skill": {
        "description": "Manage local skills — list, add, remove, search, edit",
        "description_long": "CRUD operations for local skills including listing, adding, removing, searching, and editing with a setup wizard.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/skill", "manage skills"],
        "capabilities": ["skill-crud", "setup-wizard"],
        "related": ["oh-my-claudecode:skillify", "superpowers:writing-skills"],
    },
    "oh-my-claudecode:learner": {
        "description": "Extract a learned skill from the current conversation",
        "description_long": "Identifies a repeatable pattern in the current conversation and extracts it into a reusable skill.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/learner", "learn from this"],
        "capabilities": ["pattern-extract", "skill-generate"],
        "related": ["oh-my-claudecode:skillify"],
    },
    "oh-my-claudecode:omc-doctor": {
        "description": "Diagnose and fix oh-my-claudecode installation issues",
        "description_long": "Runs diagnostic checks on the OMC installation and provides fixes for common issues.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/omc-doctor", "omc doctor"],
        "capabilities": ["diagnostic", "auto-fix", "health-check"],
        "related": ["oh-my-claudecode:omc-setup"],
    },
    "oh-my-claudecode:remember": {
        "description": "Review reusable knowledge and route to appropriate storage",
        "description_long": "Reviews reusable project knowledge and decides whether it belongs in project memory, notepad, or durable documentation.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/remember"],
        "capabilities": ["knowledge-route", "memory-write", "notepad-write"],
        "related": ["memo", "context"],
    },
    "oh-my-claudecode:plan": {
        "description": "Strategic planning with optional interview workflow",
        "description_long": "Creates strategic execution plans with optional interview-based requirement gathering. Supports --consensus and --review modes.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/plan", "plan this"],
        "capabilities": ["strategic-plan", "interview", "consensus-mode"],
        "related": ["oh-my-claudecode:ralplan", "superpowers:writing-plans"],
    },
    "oh-my-claudecode:self-improve": {
        "description": "Autonomous evolutionary code improvement with tournament selection",
        "description_long": "Runs autonomous code improvement iterations using tournament selection to evolve better solutions.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/self-improve"],
        "capabilities": ["tournament-select", "evolutionary", "auto-improve"],
        "related": ["oh-my-claudecode:autopilot"],
    },
    "oh-my-claudecode:project-session-manager": {
        "description": "Worktree-first dev environment for issues, PRs, features",
        "description_long": "Manages development environments using worktree-first approach for issues, PRs, and features with optional tmux sessions.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/project-session-manager"],
        "capabilities": ["worktree-manage", "issue-track", "tmux-session"],
        "related": ["superpowers:using-git-worktrees"],
    },
    "oh-my-claudecode:wiki": {
        "description": "LLM Wiki — persistent markdown knowledge base",
        "description_long": "Manages the LLM Wiki persistent markdown knowledge base that compounds knowledge across sessions (Karpathy model).",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/wiki"],
        "capabilities": ["wiki-manage", "knowledge-compound"],
        "related": ["wiki-ingest", "wiki-lint"],
    },
    "oh-my-claudecode:visual-verdict": {
        "description": "Structured visual QA for screenshot-to-reference comparisons",
        "description_long": "Provides structured visual QA verdicts when comparing screenshots to reference designs.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/visual-verdict"],
        "capabilities": ["screenshot-compare", "visual-qa", "structured-verdict"],
        "related": ["oh-my-claudecode:verify"],
    },
    "oh-my-claudecode:ai-slop-cleaner": {
        "description": "Clean AI-generated code slop with deletion-first workflow",
        "description_long": "Cleans AI-generated code using regression-safe, deletion-first workflow. Optional reviewer-only mode.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/ai-slop-cleaner"],
        "capabilities": ["slop-detect", "deletion-first", "regression-safe"],
        "related": ["simplify"],
    },
    "oh-my-claudecode:skillify": {
        "description": "Turn a repeatable workflow into a reusable OMC skill draft",
        "description_long": "Extracts a repeatable workflow pattern from the current session and generates a reusable OMC skill draft.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/skillify"],
        "capabilities": ["workflow-extract", "skill-draft", "template-generate"],
        "related": ["oh-my-claudecode:learner", "oh-my-claudecode:skill"],
    },
    "oh-my-claudecode:writer-memory": {
        "description": "Agentic memory for writers — characters, relationships, scenes",
        "description_long": "Tracks characters, relationships, scenes, and themes for creative writing projects.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/writer-memory"],
        "capabilities": ["character-track", "relationship-map", "scene-manage"],
        "related": [],
    },
    "oh-my-claudecode:setup": {
        "description": "Install/update routing for OMC setup flows",
        "description_long": "Entry point that routes setup, doctor, or MCP requests to the correct OMC setup flow.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/setup"],
        "capabilities": ["setup-route", "install", "update"],
        "related": ["oh-my-claudecode:omc-setup", "oh-my-claudecode:omc-doctor"],
    },
    # ── Config ──
    "update-config": {
        "description": "Configure Claude Code settings.json",
        "description_long": "Modifies Claude Code harness settings. Handles hooks, automated behaviors, and configuration changes via settings.json.",
        "source": "plugin:update-config",
        "triggers": ["/update-config", "설정 변경"],
        "capabilities": ["settings-edit", "hook-config", "behavior-automate"],
        "related": ["keybindings-help"],
    },
    "keybindings-help": {
        "description": "Customize keyboard shortcuts and keybindings",
        "description_long": "Helps customize keyboard shortcuts, rebind keys, add chord bindings, or modify ~/.claude/keybindings.json.",
        "source": "plugin:keybindings-help",
        "triggers": ["/keybindings-help", "rebind keys", "keyboard shortcut"],
        "capabilities": ["keybind-edit", "chord-bind", "shortcut-customize"],
        "related": ["update-config"],
    },
    "hook-skip-pattern": {
        "description": "Manage session-end-log.sh SKIP_PATTERNS with JSONL testing",
        "description_long": "Manages SKIP_PATTERNS in session-end-log.sh and tests them against JSONL files for immediate validation.",
        "source": "plugin:hook-skip-pattern",
        "triggers": ["/hook-skip-pattern"],
        "capabilities": ["pattern-manage", "jsonl-test"],
        "related": ["update-config"],
    },
    # ── Communication ──
    "kakaotalk:kakaotalk": {
        "description": "Send/read KakaoTalk messages on macOS",
        "description_long": "Sends and reads KakaoTalk messages using macOS automation. Supports message composition and chat reading.",
        "source": "plugin:kakaotalk",
        "triggers": ["카톡 보내줘", "카카오톡 메시지", "채팅 읽어줘"],
        "capabilities": ["message-send", "message-read", "macos-automation"],
        "related": [],
    },
    "kakaotalk": {
        "description": "KakaoTalk messaging (shorthand)",
        "description_long": "Shorthand alias for kakaotalk:kakaotalk.",
        "source": "plugin:kakaotalk",
        "triggers": ["카톡"],
        "capabilities": ["message-send", "message-read"],
        "related": ["kakaotalk:kakaotalk"],
    },
    # ── Coaching ──
    "coach-changjun": {
        "description": "1:1 coaching agent based on Kim Chang-jun methodology",
        "description_long": "Provides 1:1 coaching using Kim Chang-jun's methodology. Helps think through personal and professional dilemmas with structured questioning.",
        "source": "custom",
        "triggers": ["/coach-changjun", "코칭해줘", "코치", "고민이 있어"],
        "capabilities": ["socratic-coaching", "dilemma-analysis", "action-planning"],
        "related": [],
    },
    # ── PM ──
    "product-psychology-for-vibe-coding": {
        "description": "Product psychology for UI/UX design — 6P, BMAP, B.I.A.S, Peak-End",
        "description_long": "Applies product psychology principles to UI/UX design: 6P Storyboard, BMAP behavior model, B.I.A.S framework, Peak-End journey map, and ethical design checks.",
        "source": "custom",
        "triggers": ["사용자 심리", "행동 설계", "전환 최적화", "UX 개선"],
        "capabilities": ["6p-storyboard", "bmap", "bias-framework", "peak-end", "ethics-check"],
        "related": ["prd", "frontend-design:frontend-design"],
    },
    # ── Utility ──
    "pdf-to-excel": {
        "description": "Extract PDF tables to styled Excel files",
        "description_long": "Extracts tabular data from PDF documents and generates styled Excel files with formatting, hyperlinks, and filters using openpyxl.",
        "source": "custom",
        "triggers": ["/pdf-to-excel", "PDF 엑셀로 변환", "표 추출"],
        "capabilities": ["pdf-parse", "excel-generate", "styling", "hyperlinks"],
        "related": [],
    },
    "visualize-notion": {
        "description": "Visual transformation of Notion pages",
        "description_long": "Transforms Notion pages into visually enhanced formats with custom styling and layout.",
        "source": "plugin:visualize-notion",
        "triggers": ["노션 시각화", "페이지 꾸며줘", "visualize notion"],
        "capabilities": ["notion-transform", "visual-enhance", "layout-design"],
        "related": ["notion-reader", "frontend-design:frontend-design"],
    },
    "my-tools": {
        "description": "Explain installed plugins, skills, and commands",
        "description_long": "Lists and explains all installed plugins, skills, and commands with usage examples and descriptions.",
        "source": "plugin:my-tools",
        "triggers": ["/my-tools", "어떤 도구가 있어", "what tools"],
        "capabilities": ["tool-list", "usage-explain"],
        "related": ["superpowers:using-superpowers"],
    },
    "simplify": {
        "description": "Review changed code for quality and efficiency",
        "description_long": "Reviews recently changed code for reuse opportunities, quality issues, and efficiency improvements, then fixes problems found.",
        "source": "plugin:simplify",
        "triggers": ["/simplify", "코드 정리"],
        "capabilities": ["code-review", "quality-check", "auto-fix"],
        "related": ["oh-my-claudecode:ai-slop-cleaner"],
    },
    "loop": {
        "description": "Run a prompt or command on a recurring interval",
        "description_long": "Executes a prompt or slash command on a recurring interval (e.g., every 5 minutes). Useful for polling, monitoring, or recurring tasks.",
        "source": "plugin:loop",
        "triggers": ["/loop", "매 N분마다", "recurring"],
        "capabilities": ["interval-run", "poll", "monitor"],
        "related": ["schedule"],
    },
    "schedule": {
        "description": "Scheduled remote agents on cron",
        "description_long": "Creates, updates, lists, or runs scheduled remote agents (triggers) that execute on a cron schedule.",
        "source": "plugin:schedule",
        "triggers": ["/schedule", "cron 설정", "scheduled task"],
        "capabilities": ["cron-create", "remote-agent", "schedule-manage"],
        "related": ["loop"],
    },
    # ── Dev ──
    "claude-api": {
        "description": "Build apps with Claude API or Anthropic SDK",
        "description_long": "Assists in building applications using the Claude API, Anthropic SDK, or Agent SDK. Triggered when code imports anthropic or @anthropic-ai/sdk.",
        "source": "plugin:claude-api",
        "triggers": ["import anthropic", "Claude API", "Anthropic SDK"],
        "capabilities": ["api-guide", "sdk-usage", "agent-sdk"],
        "related": [],
    },
    # ── Aliases that might appear ──
    "autopilot": {
        "description": "Alias for oh-my-claudecode:autopilot",
        "description_long": "Shorthand alias for oh-my-claudecode:autopilot.",
        "source": "plugin:oh-my-claudecode",
        "triggers": ["/autopilot"],
        "capabilities": ["autonomous-execution"],
        "related": ["oh-my-claudecode:autopilot"],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_category(skill_name: str) -> str:
    """Determine category for a skill, using prefix-based inference as fallback."""
    if skill_name in CATEGORIES:
        return CATEGORIES[skill_name]
    # Prefix-based inference
    if skill_name.startswith("oh-my-claudecode:"):
        return "omc"
    if skill_name.startswith("superpowers:"):
        return "superpowers"
    if skill_name.startswith("session-wrap:"):
        return "workflow"
    if skill_name.startswith("clarify:"):
        return "productivity"
    if skill_name.startswith("kakaotalk:"):
        return "communication"
    if skill_name.startswith("frontend-design:"):
        return "design"
    if skill_name.startswith("google-calendar:"):
        return "productivity"
    if skill_name.startswith("interactive-review:"):
        return "workflow"
    return "other"


def parse_history(days: int) -> Counter:
    """Source 1: Parse ~/.claude/history.jsonl for slash commands."""
    counts: Counter = Counter()
    if not HISTORY_FILE.exists():
        return counts

    cutoff_ms = (time.time() - days * 86400) * 1000

    with open(HISTORY_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = entry.get("timestamp", 0)
            if ts < cutoff_ms:
                continue

            display = entry.get("display", "").strip()
            if not display.startswith("/") or display.startswith("/Users/"):
                continue

            # Extract command name (first token, strip leading /)
            cmd = display.split()[0].lstrip("/").rstrip()
            if not cmd:
                continue

            # Exclude built-in CLI commands
            base_cmd = cmd.split(":")[0] if ":" not in cmd else cmd
            if base_cmd in BUILTIN_COMMANDS:
                continue
            # Also check the part before colon for namespaced builtins
            if cmd.split(":")[0] in BUILTIN_COMMANDS:
                continue

            counts[cmd] += 1

    return counts


def parse_skill_usage(days: int) -> Counter:
    """Source 2: Parse ~/.claude/logs/skill-usage.jsonl."""
    counts: Counter = Counter()
    if not SKILL_USAGE_FILE.exists():
        return counts

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    with open(SKILL_USAGE_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts_str = entry.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                ts_utc = ts.astimezone(timezone.utc)
            except (ValueError, TypeError):
                continue

            if ts_utc < cutoff:
                continue

            skill = entry.get("skill", "").strip()
            if skill:
                counts[skill] += 1

    return counts


def parse_session_files(days: int) -> Counter:
    """Source 3: Parse session JSONL files for Skill tool invocations."""
    counts: Counter = Counter()
    if not PROJECTS_DIR.exists():
        return counts

    # Use find to limit file scan
    try:
        result = subprocess.run(
            ["find", str(PROJECTS_DIR), "-name", "*.jsonl", "-mtime", f"-{days}"],
            capture_output=True, text=True, timeout=30,
        )
        files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return counts

    for fpath in files:
        try:
            with open(fpath, encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if entry.get("type") != "assistant":
                        continue

                    content = entry.get("message", {}).get("content", [])
                    if not isinstance(content, list):
                        continue

                    for msg in content:
                        if (
                            isinstance(msg, dict)
                            and msg.get("type") == "tool_use"
                            and msg.get("name") == "Skill"
                        ):
                            skill = msg.get("input", {}).get("skill", "").strip()
                            if skill:
                                counts[skill] += 1
        except (OSError, UnicodeDecodeError):
            continue

    return counts


def merge_counts(*counters: Counter) -> dict[str, int]:
    """Merge strategy: max(source1, source2, source3) per skill."""
    all_skills = set()
    for c in counters:
        all_skills.update(c.keys())

    merged = {}
    for skill in all_skills:
        merged[skill] = max(c.get(skill, 0) for c in counters)
    return merged


def build_skills_list(usage: dict[str, int]) -> list[dict]:
    """Build the full skills list from registry + any discovered skills."""
    skills = []
    seen = set()

    # First: all registry skills
    for name, meta in SKILL_REGISTRY.items():
        cat = get_category(name)
        use_count = usage.get(name, 0)
        skills.append({
            "name": name,
            "category": cat,
            "description": meta["description"],
            "description_long": meta.get("description_long", meta["description"]),
            "usage": use_count,
            "status": "active" if use_count > 0 else "unused",
            "source": meta.get("source", "unknown"),
            "triggers": meta.get("triggers", []),
            "capabilities": meta.get("capabilities", []),
            "related": meta.get("related", []),
        })
        seen.add(name)

    # Then: any skills found in usage but not in registry
    for name, count in usage.items():
        if name not in seen:
            cat = get_category(name)
            skills.append({
                "name": name,
                "category": cat,
                "description": f"Skill: {name}",
                "description_long": f"Discovered skill: {name} (not in registry)",
                "usage": count,
                "status": "active" if count > 0 else "unused",
                "source": "unknown",
                "triggers": [f"/{name}"],
                "capabilities": [],
                "related": [],
            })

    # Sort: active skills first (by usage desc), then unused (alphabetical)
    skills.sort(key=lambda s: (-s["usage"], s["name"]))
    return skills


def build_categories(skills: list[dict]) -> list[dict]:
    """Build category summary from skills list."""
    cat_data: dict[str, dict] = {}
    for s in skills:
        cat = s["category"]
        if cat not in cat_data:
            cat_data[cat] = {"count": 0, "execution_count": 0}
        cat_data[cat]["count"] += 1
        cat_data[cat]["execution_count"] += s["usage"]

    categories = []
    for cat_id in sorted(cat_data.keys(), key=lambda c: -cat_data[c]["execution_count"]):
        categories.append({
            "id": cat_id,
            "label": CATEGORY_LABELS.get(cat_id, cat_id.capitalize()),
            "color": CATEGORY_COLORS.get(cat_id, "#9CA0A8"),
            "count": cat_data[cat_id]["count"],
            "execution_count": cat_data[cat_id]["execution_count"],
        })
    return categories


def build_recommendations(skills: list[dict]) -> dict:
    """Build recommendations based on usage patterns."""
    used_cats = Counter()
    unused_skills = []
    for s in skills:
        if s["usage"] > 0:
            used_cats[s["category"]] += s["usage"]
        else:
            unused_skills.append(s)

    # Top 3 user categories by execution count
    top_cats = [cat for cat, _ in used_cats.most_common(3)]

    high = []
    medium = []

    for s in unused_skills:
        # Skip aliases/shorthands
        if "shorthand" in s.get("description_long", "").lower() or "alias" in s.get("description_long", "").lower():
            continue

        if s["category"] in top_cats:
            high.append({
                "name": s["name"],
                "reason": f"Unused skill in your top category '{s['category']}'. {s['description']}",
            })
        else:
            # Only include skills with clear utility
            if s["category"] not in ("other",) and len(s.get("capabilities", [])) > 0:
                medium.append({
                    "name": s["name"],
                    "reason": f"{s['description']}. Category: {s['category']}.",
                })

    # Limit recommendations
    high = high[:8]
    medium = medium[:8]

    suggested_new = [
        {
            "name": "gov-program-research",
            "description": "Automated government/institutional support program research and archiving",
            "reason": "Identified in backlog: manual research of 8+ programs took ~1 hour. Automates extraction of program name, eligibility, funding, deadlines, and application URLs into consistent schema.",
            "predicted_capabilities": ["web-search", "schema-extract", "md-archive", "calendar-deadline"],
            "suggested_triggers": ["지원사업 조사해줘", "영진위 프로그램 찾아줘", "gov program research"],
            "evidence": ["MEMORY.md backlog item", "2/17 session: 영진위 8+ programs manual research ~1hr"],
        },
        {
            "name": "notion-to-obsidian-sync",
            "description": "Automated Notion-to-Obsidian sync combining meeting + notion-reader patterns",
            "reason": "The meeting and notion-reader skills are both heavily used. A unified sync skill would automate the recurring pattern of pulling Notion content into Obsidian.",
            "predicted_capabilities": ["notion-read", "obsidian-write", "template-match", "conflict-detect"],
            "suggested_triggers": ["노션 싱크", "sync notion", "노션에서 옵시디언으로"],
            "evidence": ["meeting skill: 18 uses", "notion-reader skill: 7 uses", "Recurring Notion->Obsidian workflow in CLAUDE.md"],
        },
        {
            "name": "weekly-class-prep",
            "description": "Automated weekly class preparation document generation for K-Arts",
            "reason": "CLAUDE.md defines a detailed Sunday prep protocol that reads all syllabi, extracts assignments, and generates weekly prep documents. Currently manual.",
            "predicted_capabilities": ["syllabus-read", "assignment-extract", "weekly-doc-generate", "calendar-check"],
            "suggested_triggers": ["주간 수업 준비", "이번주 수업", "weekly prep"],
            "evidence": ["CLAUDE.md 주간 수업 준비 프로토콜", "9 courses / 18 credits tracked", "과제-트래커.md active use"],
        },
    ]

    return {
        "high": high,
        "medium": medium,
        "suggested_new": suggested_new,
    }


def build_summary(skills: list[dict]) -> dict:
    """Build summary statistics."""
    total = len(skills)
    used = sum(1 for s in skills if s["usage"] > 0)
    total_exec = sum(s["usage"] for s in skills)
    top = max(skills, key=lambda s: s["usage"]) if skills else {"name": "none", "usage": 0}

    return {
        "total_skills": total,
        "used_count": used,
        "total_executions": total_exec,
        "top_skill": {"name": top["name"], "count": top["usage"]},
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate Claude Code skill usage data")
    parser.add_argument("--days", type=int, default=30, help="Number of days to scan (default: 30)")
    args = parser.parse_args()

    print(f"Scanning {args.days} days of skill usage data...")

    # Collect from all sources
    src1 = parse_history(args.days)
    src2 = parse_skill_usage(args.days)
    src3 = parse_session_files(args.days)

    print(f"  Source 1 (history.jsonl): {sum(src1.values())} invocations across {len(src1)} skills")
    print(f"  Source 2 (skill-usage.jsonl): {sum(src2.values())} invocations across {len(src2)} skills")
    print(f"  Source 3 (session files): {sum(src3.values())} invocations across {len(src3)} skills")

    # Merge
    usage = merge_counts(src1, src2, src3)
    print(f"  Merged: {sum(usage.values())} invocations across {len(usage)} unique skills")

    # Build output
    skills = build_skills_list(usage)
    categories = build_categories(skills)
    recommendations = build_recommendations(skills)
    summary = build_summary(skills)

    output = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "period_days": args.days,
        "summary": summary,
        "categories": categories,
        "skills": skills,
        "recommendations": recommendations,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nOutput written to {OUTPUT_FILE}")
    print(f"  Total skills: {summary['total_skills']}")
    print(f"  Used: {summary['used_count']}")
    print(f"  Total executions: {summary['total_executions']}")
    print(f"  Top skill: {summary['top_skill']['name']} ({summary['top_skill']['count']})")


if __name__ == "__main__":
    main()
