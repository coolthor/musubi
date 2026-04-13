"""Built-in concept dictionary + user-concept loader.

The default dictionary is intentionally **generic tech-stack terms** — things
any developer with an LLM inference / web dev / notes workflow would care
about. Domain-specific terms (your trading vocabulary, internal product
names, team member names, etc.) should live in a user concepts file:

    $XDG_CONFIG_HOME/musubi/concepts.txt       # default location
    $MUSUBI_CONCEPTS_FILE                       # override path

One concept per line. Lines starting with `#` are comments. Multi-word
concepts are fine — they're matched as exact phrases.
"""
from __future__ import annotations

from pathlib import Path

# Generic default dictionary. Safe to ship publicly — no personal or
# proprietary terms. Users extend via $MUSUBI_CONCEPTS_FILE.
DEFAULT_CONCEPTS: set[str] = {
    # LLM inference runtimes
    "vllm", "ollama", "llama.cpp", "text-generation-inference", "tgi",
    "sglang", "exllamav2", "mlx", "mlc-llm", "candle",
    # Cloud / hardware
    "cuda", "rocm", "gpu", "vram", "nvidia", "amd", "intel",
    "rtx", "h100", "a100", "l40", "l4", "v100", "t4",
    "mac", "macbook", "apple silicon", "metal", "m1", "m2", "m3", "m4",
    "arm64", "x86", "tailscale", "cloudflare", "ssh", "docker",
    "kubernetes", "k8s", "orbstack", "podman",
    # Models
    "llama", "llama 2", "llama 3", "llama 4",
    "qwen", "qwen2", "qwen3", "mistral", "mixtral", "phi", "gemma",
    "gpt-oss", "nemotron", "deepseek", "glm",
    "claude", "claude opus", "claude sonnet", "claude haiku",
    "gpt-4", "gpt-5", "o1", "o3", "chatgpt", "openai", "anthropic",
    "gemini", "perplexity",
    # Architecture concepts
    "moe", "mixture of experts", "dense", "transformer", "attention",
    "mamba", "ssm", "state space", "hybrid",
    "rope", "alibi", "grouped query attention", "gqa",
    "sliding window", "flash attention", "paged attention",
    # Quantization & optimization
    "fp32", "fp16", "bf16", "fp8", "fp4", "nvfp4", "int8", "int4",
    "q4", "q5", "q6", "q8", "gguf", "awq", "gptq", "marlin", "cutlass",
    "kv cache", "prefix caching", "chunked prefill", "speculative decoding",
    "quantization", "pruning", "distillation", "fine-tuning",
    # Serving & inference
    "inference", "serving", "batch", "throughput", "latency",
    "tok/s", "ttft", "tpot", "context window", "context length",
    "max tokens", "max_model_len",
    # Agents & tooling
    "agent", "multi-agent", "orchestrator", "planner", "executor",
    "tool calling", "function calling", "mcp", "mcp server",
    "prompt", "prompt engineering", "system prompt",
    "skill", "hook", "workflow",
    # Claude Code ecosystem
    "claude code", "cursor", "cline", "aider", "opencode",
    # Web & app dev
    "react", "next.js", "svelte", "vue", "solid",
    "typescript", "javascript", "python", "rust", "go", "swift", "kotlin",
    "tailwind", "css", "html", "mdx", "rss", "sitemap",
    "postgres", "postgresql", "sqlite", "mysql", "redis", "valkey",
    "supabase", "vercel", "netlify", "fly.io",
    # RAG & retrieval
    "rag", "embedding", "vector search", "bm25", "reranking",
    "knowledge graph", "ontology", "retrieval",
    # Ops concepts
    "cron", "scheduler", "webhook", "websocket", "sse",
    "ci/cd", "github actions", "deploy", "rollback", "migration",
    "error handling", "debugging", "logging", "observability", "tracing",
    "auth", "oauth", "jwt", "session", "token", "api key",
    "rate limiting", "permission", "rbac", "security",
    # SEO / content
    "seo", "geo", "aeo", "canonical", "hreflang", "og image",
    "search console", "analytics",
    # Git workflow
    "git", "commit", "branch", "merge", "rebase", "worktree",
}

# Path-to-concept map: if a document's path contains one of these keys,
# the matching concepts are added to that document's concept set. Generic
# enough to ship publicly.
DEFAULT_PATH_CONCEPTS: dict[str, set[str]] = {
    "experience-": {"experience", "gotcha"},
    "session-": {"session", "work log"},
    "deploy": {"deploy", "ci/cd"},
    "migration": {"migration", "upgrade"},
    "benchmark": {"benchmark", "inference"},
    "scheduler": {"scheduler", "cron"},
    "security": {"security"},
    "vllm": {"vllm", "inference", "serving"},
    "ollama": {"ollama", "inference"},
    "agent": {"agent"},
}


def _parse_concept_file(path: Path) -> set[str]:
    concepts: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        import sys
        print(
            f"Warning: {path} is not valid UTF-8, skipping user concepts",
            file=sys.stderr,
        )
        return concepts
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        concepts.add(stripped.lower())
    return concepts


def load_concepts(extra_file: Path | None = None) -> set[str]:
    """Return the full concept set: defaults + optional user extension."""
    concepts = set(DEFAULT_CONCEPTS)
    if extra_file and extra_file.exists():
        concepts |= _parse_concept_file(extra_file)
    return concepts


def load_path_concepts() -> dict[str, set[str]]:
    """Path-based concept rules. Currently only the built-in map is used.

    Users can customize by overriding `musubi.builder.PATH_CONCEPT_RULES` at
    runtime, or by extending via a future config option.
    """
    return {k: set(v) for k, v in DEFAULT_PATH_CONCEPTS.items()}
