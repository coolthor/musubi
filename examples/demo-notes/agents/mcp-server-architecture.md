---
title: "MCP Server Architecture: Tools as a Service"
date: "2026-03-15"
tags: ["mcp", "agent", "tool calling", "architecture"]
---

## What MCP Is

Model Context Protocol (MCP) is a standardized way to expose tools and
data sources to AI agents. Think of it as "USB-C for AI" — any MCP
client can connect to any MCP server, regardless of the underlying
model or framework.

## Key Design Decisions

1. **Transport**: stdio (local) or HTTP (remote). stdio is simpler for
   single-machine setups; HTTP enables shared tool servers.
2. **Tool granularity**: one tool per focused action. Don't build a
   mega-tool that does 10 things — build 10 tools that do 1 thing each.
3. **Schema matters**: well-typed JSON Schema parameters let the model
   call your tools correctly without examples in the prompt.

## When NOT to Use MCP

If the tool is a simple shell command (`git status`, `ls`), just let
the agent call it via a shell tool. MCP adds value when the tool needs
structured input/output, authentication, or cross-session state.
