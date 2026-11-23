"""Constants, regexes, and immutable/mutable dataclasses for the Crucible Domain RAM index."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_GLOBAL_CONFIG_DIR = Path.home() / ".gemini" / "config"

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "for",
        "from",
        "how",
        "i",
        "in",
        "into",
        "is",
        "it",
        "my",
        "need",
        "of",
        "on",
        "or",
        "should",
        "that",
        "the",
        "this",
        "to",
        "use",
        "what",
        "when",
        "where",
        "which",
        "who",
        "with",
        "write",
    }
)

ROLE_CARD_CODES = (
    "COM-D",
    "COM-M",
    "COM-S",
    "MKT-D",
    "MKT-M",
    "MKT-S",
    "CNT-D",
    "CNT-M",
    "CNT-S",
    "PROD-D",
    "PROD-M",
    "PROD-S",
)

# Host-agnostic mapping from legacy ChatGPT skill IDs to canonical local IDs.
CHATGPT_SKILL_BINDINGS: dict[str, dict[str, Any]] = {
    "6a88759040a88191a896614be5d93a01": {
        "label": "Shape media brief",
        "targets": ["MW-01", "OP-01"],
    },
    "6ad142fb15388191a1634e7da79674dc": {
        "label": "Write video concept",
        "targets": ["MW-02", "MP-01"],
    },
    "6a8875c54d3c81919a7f6de589f82d02": {
        "label": "Write A/V script",
        "targets": ["MW-04"],
        "host_skills": ["av-craft"],
    },
    "6a8875e68af88191940f923dd303141b": {
        "label": "Plan media production",
        "targets": ["MP-01", "MP-02", "MP-03", "MP-04"],
    },
    "6af01c95eb148191b50f2ee390de4170": {
        "label": "Prepare media workback",
        "targets": ["OP-03"],
    },
    "6a8875fd6f8c81918cd0bd3934e74711": {
        "label": "Audit media release",
        "targets": ["MP-10", "MP-11", "CH-03", "CH-04"],
    },
    "6acfae059d5881918e34ff0b0a55f8b6": {
        "label": "Investigate with evidence",
        "targets": ["CD-01", "MK-02"],
    },
    "6add61269f9081919a9eb9e24f7aae64": {
        "label": "Recover working practice",
        "targets": ["OP-08", "ig-discover-method"],
    },
    "6add61c97c0c8191bc6cb4f84a1f3312": {
        "label": "Trial practice in use",
        "targets": ["OP-08", "ig-improve"],
    },
    "6afa4e6d26a08191bd80f1926eddb3bc": {
        "label": "Create Work Graphs",
        "targets": ["WOS-GRAPH", "K-GRAPH-01"],
    },
}

CORE_ENTRY_DOCS: dict[str, tuple[str, str, str]] = {
    "WOS-GRAPH": (
        "Work Operating System Graph Catalog (7 Graph Types)",
        "Project/Work Operating System/Work_Operating_System_Graph_Catalog.md",
        "Choose a graph type (capability, process, decision, dependency, trace, outcome, target architecture) with Mermaid examples.",
    ),
    "WOS-README": (
        "Work Operating System Entry Point",
        "Project/Work Operating System/README.md",
        "Plan, delegate, execute, and review digital work across roles and forks.",
    ),
    "MA-ROUTING": (
        "Media Work Routing",
        "Knowledge/Media Agency/Media_Work_Routing.md",
        "Choose responsible Media Agency discipline, level, and method by incoming work object.",
    ),
    "MA-SKILLS": (
        "Media Agency Skills and Workflows Catalogue",
        "Knowledge/Media Agency/Skills and Workflows/README.md",
        "Lookup index of all 55 Media Agency procedures across writing, production, campaigns, comms, channel, and portfolio.",
    ),
    "IG-README": (
        "Inner Gravity Harness Self-Model",
        "Project/Inner Gravity/README.md",
        "Seven-graph map, install_pack specs, and verification evidence for Antigravity inside Crucible Domain.",
    ),
    "CRUCIBLE-ATLAS": (
        "Crucible Domain System Atlas & Neon Handoff",
        "Graphs/00_System_Atlas_and_Neon_Handoff.md",
        "O(1) file-to-purpose lookup table, capability atlas, and cross-domain entry point.",
    ),
    "CRUCIBLE-AUDIT": (
        "Crucible Coupling & Reachability Audit",
        "Graphs/02_Coupling_and_Reachability_Audit.md",
        "Over-coupled, under-coupled, and misplaced component ledger across Crucible Domain.",
    ),
    "IG-OBS": (
        "Inner Gravity Whole-System Observatory & Causal Trace",
        "Project/Inner Gravity/05_Session_4188f88a_Causal_Trace_and_Gaps.md",
        "Live observatory topology, session 4188f88a causal trace, and honest weakness ledger.",
    ),
    "CPL-PILOT-MAPS": (
        "Crucible x CPL Pilot & Calendar Maps (Planning Reference)",
        "Archive/overnight_mvp/cpl_pilot_maps.md",
        "Historical planning reference for CPL pilot and content calendar maps archived from Inner Gravity.",
    ),
    "TEST-PHIL": (
        "Testing Philosophy & 4 Evidence Rungs",
        "Knowledge/Testing_Philosophy.md",
        "Four Evidence Rungs, 3 Non-Negotiable Test Laws, red-first/mutation kills, and Rung-3 planted-defect evals (K-TEST-01).",
    ),
}

CANONICAL_LOCAL_FIRST_FILES = (
    "README.md",
    "Knowledge/Media Agency/Skills and Workflows/README.md",
    "Knowledge/Media Agency/Media_Work_Routing.md",
    "Knowledge/Knowledge_Register.md",
    "Knowledge/Testing_Philosophy.md",
    "Calgary Public Library/GROUND_TRUTH.md",
    "Personal Work/GROUND_TRUTH.md",
    "Project/Project_Register.md",
    "Archive/README.md",
    "Graphs/GROUND_TRUTH.md",
    "Graphs/00_System_Atlas_and_Neon_Handoff.md",
)

EXHIBIT_LESSON_LINKS: dict[str, tuple[str, ...]] = {
    "A02": ("K-ARCH-03",),
    "A03": ("K-WOS-03",),
    "A04": ("K-ARCH-02",),
    "A05": ("K-WOS-03",),
    "A06": ("K-SIDECAR-01", "K-ARCH-02"),
    "A07": ("K-STORY-01",),
    "A08": ("K-WOS-03",),
    "A09": ("K-ARCH-01",),
    "A10": ("K-ARCH-03", "K-WOS-03"),
}

PROC_HEADING_RE = re.compile(r"^#{1,4}\s+((?:MW|MP|MK|CD|CH|OP)-\d+)\b[:\s·—-]*(.*)$")
TABLE_ROW_RE = re.compile(r"^\|\s*([KPAC]-\S+?)\s*\|\s*(.*)$")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
BARE_URL_RE = re.compile(r"https?://[^\s)>\"'`]+")
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")

PRIMITIVE_VALID_STATUSES = frozenset({"WIRED_HERE", "EXTERNAL_PROVEN", "PROTOTYPE"})
PRIMITIVE_REQUIRED_KEYS = (
    "id",
    "name",
    "family",
    "domains",
    "inputs",
    "mechanism",
    "outputs",
    "breakpoints",
    "status",
    "sources",
    "receiving_check",
)

FORGE_DOMAINS = ("systems", "media", "writing", "worldbuilding", "general")

FORGE_MEDIA_CUES = frozenset(
    {
        "video",
        "audio",
        "clip",
        "footage",
        "shoot",
        "camera",
        "youtube",
        "motion",
        "graphics",
        "documentary",
        "offload",
        "checksum",
        "dit",
        "av",
        "script",
        "thumbnail",
        "campaign",
        "channel",
    }
)
FORGE_WRITING_CUES = frozenset(
    {
        "cover",
        "letter",
        "resume",
        "brief",
        "executive",
        "commission",
        "editorial",
        "draft",
        "document",
        "author",
        "prose",
    }
)
FORGE_WORLDBUILDING_CUES = frozenset(
    {
        "world",
        "canon",
        "character",
        "faction",
        "scene",
        "lore",
        "narrative",
        "story",
        "rpg",
    }
)
FORGE_SYSTEMS_CUES = frozenset(
    {
        "wos",
        "workflow",
        "receiving",
        "checkpoint",
        "resume",
        "sqlite",
        "sidecar",
        "retrieval",
        "ast",
        "hook",
        "gate",
        "test",
        "ci",
        "repo",
        "kernel",
        "graph",
        "cli",
        "schema",
        "contract",
        "python",
        "rust",
        "audit",
        "reachability",
        "melt",
    }
)
FORGE_MEDIA_OVERRIDE_CUES = frozenset({"av", "documentary", "footage", "clip", "video", "audio", "custody"})
MEDIA_AGENCY_ID_PREFIXES = ("mk-", "cd-", "ch-", "mw-", "mp-", "op-", "com-", "mkt-", "cnt-", "prod-")

MAX_MELT_SCAN_REPOS = 5
MAX_SAMPLE_PATHS = 20
MAX_README_EXCERPT_CHARS = 280
MAX_STDOUT_BYTES_PER_REPO = 1200
STUB_DISK_KB_THRESHOLD = 5

ACTIVE_HUB_REPOS = frozenset({"crucible-domain", "antigravity-config", "work-operating-system"})

IGNORED_TREE_DIRS = frozenset(
    {
        "node_modules",
        ".git",
        "dist",
        "build",
        ".venv",
        "venv",
        "__pycache__",
        ".next",
        "target",
        "vendor",
        ".pytest_cache",
        ".mypy_cache",
    }
)

ASSET_OR_BINARY_EXTS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".wav",
    ".mp3",
    ".flac",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pdf",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".pyc",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
)

CODE_EXTS = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".rs",
    ".go",
    ".sh",
    ".ps1",
    ".sql",
    ".html",
    ".css",
    ".c",
    ".cpp",
    ".h",
    ".java",
    ".rb",
)

MANIFEST_FILENAMES = frozenset(
    {
        "pyproject.toml",
        "requirements.txt",
        "setup.py",
        "package.json",
        "cargo.toml",
        "go.mod",
        "dockerfile",
        "docker-compose.yml",
        "makefile",
    }
)

ENTRYPOINT_BASENAMES = frozenset(
    {
        "main.py",
        "cli.py",
        "app.py",
        "server.py",
        "index.py",
        "index.ts",
        "index.tsx",
        "index.js",
        "main.ts",
        "main.rs",
        "lib.rs",
        "skill.md",
        "hooks.json",
    }
)

MONTH_NAME_TO_NUM = {
    "january": "01",
    "february": "02",
    "march": "03",
    "april": "04",
    "may": "05",
    "june": "06",
    "july": "07",
    "august": "08",
    "september": "09",
    "october": "10",
    "november": "11",
    "december": "12",
}


@dataclass(frozen=True)
class CapabilityEntry:
    """Single indexed local capability, role, knowledge lesson, project, exhibit, or skill."""

    id: str
    kind: str  # procedure | role | knowledge | project | exhibit | doc | skill
    title: str
    path: str
    line: int = 1
    domain: str = ""
    summary: str = ""
    use_when: str = ""
    related_ids: tuple[str, ...] = ()
    reachability: str = "local"  # local | slash_only | host_global
    mechanisms: str = ""
    breakpoints: str = ""
    transfers: str = ""
    limit_or_action: str = ""


@dataclass(frozen=True)
class BindingStatus:
    """Resolved status for one external ChatGPT skill ID."""

    skill_id: str
    label: str
    target_ids: tuple[str, ...]
    resolved_paths: tuple[str, ...]
    missing_targets: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return bool(self.target_ids) and not self.missing_targets


@dataclass
class CapabilityIndex:
    """In-memory index of all reachable Crucible Domain capabilities and bindings."""

    root: Path
    entries: dict[str, CapabilityEntry]
    alias_map: dict[str, str]
    chatgpt_bindings: dict[str, BindingStatus]
    skill_frontmatter_bytes: int
    build_ms: float
    counts_by_kind: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class RouteMatch:
    """One ranked match from route_query."""

    entry: CapabilityEntry
    score: float
    matched_via: str


@dataclass(frozen=True)
class RouteResult:
    """Result returned by route_query with explicit abstention signal."""

    query: str
    match_mode: str  # exact | chatgpt_binding | lexical | abstained
    abstained: bool
    reason: str
    matches: list[RouteMatch]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "match_mode": self.match_mode,
            "abstained": self.abstained,
            "reason": self.reason,
            "matches": [
                {
                    "id": m.entry.id,
                    "kind": m.entry.kind,
                    "title": m.entry.title,
                    "path": m.entry.path,
                    "line": m.entry.line,
                    "reachability": m.entry.reachability,
                    "score": round(m.score, 3),
                    "matched_via": m.matched_via,
                    "summary": m.entry.summary,
                    "related_ids": list(m.entry.related_ids),
                }
                for m in self.matches
            ],
        }


@dataclass(frozen=True)
class DiagnosticFinding:
    """Single closed-loop verification finding from run_doctor."""

    category: str
    severity: str  # PASS | WARN | FAIL | INFO
    subject: str
    detail: str
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DoctorReport:
    """Full workspace + host reachability health report."""

    root: str
    findings: list[DiagnosticFinding]
    metrics: dict[str, Any]

    @property
    def fail_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "FAIL")

    @property
    def warn_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "WARN")

    @property
    def pass_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "PASS")

    @property
    def ok(self) -> bool:
        return self.fail_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "ok": self.ok,
            "summary": {
                "pass": self.pass_count,
                "warn": self.warn_count,
                "fail": self.fail_count,
            },
            "metrics": self.metrics,
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass(frozen=True)
class ForgeBrief:
    """In-RAM prior-art, lesson, project-home, and falsifiable verification synthesis for building new systems."""

    problem: str
    abstained: bool
    reason: str
    build_ms: float
    existing_projects: list[dict[str, Any]]
    prior_systems: list[dict[str, Any]]
    governing_lessons: list[dict[str, Any]]
    procedures_and_roles: list[dict[str, Any]]
    verification_requirements: list[str]
    domain_scope: str = "general"
    primitive_stack: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
