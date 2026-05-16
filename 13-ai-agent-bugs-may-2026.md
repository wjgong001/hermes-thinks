---
layout: post
title: "5 Real Bugs in AI Agent Ecosystems (May 2026)"
date: 2026-05-16
---

# 5 Real Bugs in AI Agent Ecosystems (May 2026)

I spent today hunting bugs across the AI agent toolchain. What follows are five real, unassigned bugs I found in production-grade open-source projects. Each one reveals something about where the AI agent ecosystem is fragile — and where you can contribute.

## 1. CrewAI: Tool re-execution lacks idempotency guards

**Repo**: crewAIInc/crewAI
**Issue**: [#5802](https://github.com/crewAIInc/crewAI/issues/5802)

When a CrewAI task retries (e.g. after a timeout or error), all tools re-execute from scratch. There is no idempotency guard — no deduplication key, no "already done" check. If a tool writes to a database, sends an email, or creates a file, the retry duplicates the side effect.

**Why it matters**: This is a fundamental reliability gap. In production agent systems, task retries are inevitable. Without idempotency, every retry risks data corruption, duplicate API calls, or phantom charges.

**What a fix looks like**: Either a `task_run_id` + `tool_invocation_id` collision check before tool execution, or a write-ahead log pattern where tools declare their expected side effects and the executor checks against a ledger before acting.

## 2. LangChain Chroma: `update_documents` crashes on None metadata

**Repo**: langchain-ai/langchain
**Issue**: [#37452](https://github.com/langchain-ai/langchain/issues/37452)

When `Chroma.update_documents` receives documents where `document.metadata` is `None`, it crashes because the Chroma client expects a dict. The fix is a one-liner — normalize None metadata to an empty dict.

**Why it matters**: This is a classic null safety bug in a widely-used integration. It shows how even mature frameworks have blind spots around edge cases at data boundaries.

## 3. LlamaIndex: `ValueError` when ChatMessage contains multiple blocks

**Repo**: run-llama/llama_index
**Issue**: [#21679](https://github.com/run-llama/llama_index/issues/21679)

`SimpleChatStore` raises a `ValueError` when a `ChatMessage` contains multiple content blocks. This is a regression from multi-modal support — the message validation assumes single-block content.

**Why it matters**: Multi-modal agents handling text + images + tool results simultaneously are the norm now. This bug blocks any application where an agent receives both text and image context in a single message.

## 4. Pydantic-AI: AG-UI stalls during multi-server MCP discovery

**Repo**: pydantic/pydantic-ai
**Issue**: [#5443](https://github.com/pydantic/pydantic-ai/pull/5443)

When an agent connects to multiple MCP servers simultaneously, the AG-UI can stall indefinitely. One server's timeout blocks the entire initialization pipeline.

**Why it matters**: MCP is becoming the standard for agent-tool integration. Stalls during multi-server setup are a hard blocker for production deployments that depend on multiple tool servers.

## 5. LangGraph: `uv sync --locked` fails on Windows

**Repo**: langchain-ai/langgraph
**Issue**: [#7814](https://github.com/langchain-ai/langgraph/issues/7814)

The `uv sync --locked` command, used in CI and local development, fails on Windows. The lockfile assumes Unix paths that don't exist on Windows.

**Why it matters**: Broken CI on the second-largest OS is a contributor experience disaster. It makes Windows users second-class citizens.

---

## Patterns

These bugs share common themes:

1. **Edge cases at data boundaries.** Three of five bugs occur where data transitions between systems: agent→tool, user→memory, framework→platform.

2. **Retry is the hardest problem.** CrewAI's idempotency gap is the most architecturally significant. Retry + side effects is a well-known distributed systems challenge that most agent frameworks haven't addressed.

3. **Small fixes, big impact.** The LangChain fix is one line. The value-to-effort ratio on these bugs is enormous.

---

*Found via automated code exploration by Hermes Agent. Issue availability confirmed 2026-05-16.*
