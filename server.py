"""
TasksAI MCP Server — Universal Multi-Vertical Router

A single MCP server that works for all 29 TasksAI verticals.
On startup, calls GET /v1/me to detect the vertical from the license key,
then self-configures tool names, system prompt, and abbreviation maps.

Tools (names are vertical-prefixed at runtime, e.g. farmertasksai_search):
  {prefix}_search     — Find the right skill for your task
  {prefix}_execute    — Get the full expert framework for a skill (costs 1 credit)
  {prefix}_balance    — Check your remaining credit balance
  {prefix}_categories — Browse skills by category

Privacy: Your queries, documents, and client data never leave your machine.
Skills run entirely locally. The API only delivers skill metadata and
counts credits — it never sees what you're working on.
"""

import os
import re
import sys
import time
import asyncio
import platform
import httpx
from pathlib import Path

# Force UTF-8 stdout/stderr on Windows (default is CP1252 which breaks emoji)
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# ── .env resolution ──────────────────────────────────────────────────────────
# When running as a compiled binary (PyInstaller), the .env lives in the
# permanent install directory, not next to the executable.
# Search order: install dir → script/exe dir → cwd

def _find_dotenv() -> str | None:
    """Return path to .env or None. Checks install dir first."""
    system = platform.system()

    # Determine app folder name from this binary's parent dir name,
    # or fall back to checking all known vertical install dirs.
    home = Path.home()
    if system == "Windows":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        search_bases = [local]
    elif system == "Darwin":
        search_bases = [home / "Library" / "Application Support"]
    else:
        search_bases = [home / ".local" / "share"]

    # Check parent of the running binary first (most specific)
    exe_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    candidate = exe_dir / ".env"
    if candidate.exists():
        return str(candidate)

    # Search known TasksAI install dirs under the base
    for base in search_bases:
        if not base.exists():
            continue
        for child in base.iterdir():
            if child.is_dir() and "tasksai" in child.name.lower():
                candidate = child / ".env"
                if candidate.exists():
                    return str(candidate)

    return None


_dotenv_path = _find_dotenv()
if _dotenv_path:
    load_dotenv(_dotenv_path)
else:
    load_dotenv()  # fallback: search cwd and parent dirs

API_BASE    = os.getenv("TASKSAI_API_BASE", os.getenv("LAWTASKSAI_API_BASE", "https://api.lawtasksai.com"))
LICENSE_KEY = os.getenv("TASKSAI_LICENSE_KEY", os.getenv("LAWTASKSAI_LICENSE_KEY", ""))
PRODUCT_ID  = os.getenv("TASKSAI_PRODUCT_ID", "")  # set by installer; used to resolve correct vertical

if not LICENSE_KEY:
    print("ERROR: License key is required. Set TASKSAI_LICENSE_KEY in your .env file.", file=sys.stderr, flush=True)
    print("Find your key in your purchase confirmation email.", file=sys.stderr, flush=True)
    sys.exit(1)

SERVER_VERSION = "2.1.0"

AUTH_HEADERS = {
    "Authorization":    f"Bearer {LICENSE_KEY}",
    "Content-Type":     "application/json",
    "X-Client-Type":    "mcp-server",
    "X-Client-Version": SERVER_VERSION,
}

# ── Per-vertical abbreviation maps ────────────────────────────────────────────
# Expands common shorthand before trigger-phrase matching.
# Fallback abbreviation maps used when GET /v1/abbreviations is unavailable.
# Sprint 6: DB is now the source of truth; these are a safety net only.

_ABBREVS_FALLBACK = {
    "law": {
        "mtc":    "motion to compel",
        "rogs":   "interrogatories",
        "rog":    "interrogatory",
        "rfa":    "request for admission",
        "rfas":   "requests for admission",
        "rfp":    "request for production",
        "rfps":   "requests for production",
        "tro":    "temporary restraining order",
        "pi":     "personal injury",
        "msj":    "motion for summary judgment",
        "msk":    "motion to strike",
        "sj":     "summary judgment",
        "jnov":   "judgment notwithstanding verdict",
        "mil":    "motion in limine",
        "sol":    "statute of limitations",
        "aff":    "affidavit",
        "decl":   "declaration",
        "depo":   "deposition",
        "deps":   "depositions",
        "frcp":   "federal rules civil procedure",
        "fre":    "federal rules evidence",
        "compl":  "complaint",
        "ans":    "answer",
        "roe":    "rules of evidence",
        "atty":   "attorney",
    },
    "realtor": {
        "mls":    "multiple listing service",
        "cma":    "comparative market analysis",
        "dom":    "days on market",
        "arv":    "after repair value",
        "hoa":    "homeowners association",
        "coe":    "close of escrow",
        "emd":    "earnest money deposit",
        "piti":   "principal interest taxes insurance",
        "ltv":    "loan to value",
        "nar":    "national association of realtors",
        "bom":    "back on market",
        "uc":     "under contract",
        "fs":     "for sale",
        "fsbo":   "for sale by owner",
        "reo":    "real estate owned",
    },
    "contractor": {
        "rfi":    "request for information",
        "sow":    "scope of work",
        "co":     "change order",
        "gc":     "general contractor",
        "ntp":    "notice to proceed",
        "pco":    "potential change order",
        "aia":    "american institute of architects",
        "lien":   "mechanics lien",
        "sub":    "subcontractor",
        "por":    "purchase order request",
        "cos":    "certificate of substantial completion",
        "punch":  "punch list",
        "g702":   "payment application",
        "g703":   "schedule of values",
    },
    "farmer": {
        "fsa":    "farm service agency",
        "nrcs":   "natural resources conservation service",
        "crp":    "conservation reserve program",
        "arc":    "agriculture risk coverage",
        "plc":    "price loss coverage",
        "usda":   "united states department of agriculture",
        "eqip":   "environmental quality incentives program",
        "csa":    "community supported agriculture",
        "gmp":    "good manufacturing practices",
        "gap":    "good agricultural practices",
    },
    "hr": {
        "pip":    "performance improvement plan",
        "pto":    "paid time off",
        "fmla":   "family medical leave act",
        "ada":    "americans with disabilities act",
        "eeoc":   "equal employment opportunity commission",
        "w2":     "wage and tax statement",
        "i9":     "employment eligibility verification",
        "cobra":  "consolidated omnibus budget reconciliation act",
        "osha":   "occupational safety and health administration",
        "erp":    "employee relations policy",
    },
    "accounting": {
        "p&l":    "profit and loss",
        "cogs":   "cost of goods sold",
        "ar":     "accounts receivable",
        "ap":     "accounts payable",
        "gaap":   "generally accepted accounting principles",
        "ytd":    "year to date",
        "mtd":    "month to date",
        "ebitda": "earnings before interest taxes depreciation amortization",
        "cpa":    "certified public accountant",
        "sox":    "sarbanes oxley",
    },
    "mortgage": {
        "ltv":    "loan to value",
        "dti":    "debt to income",
        "arm":    "adjustable rate mortgage",
        "apr":    "annual percentage rate",
        "pmi":    "private mortgage insurance",
        "hud":    "housing and urban development",
        "fnma":   "fannie mae",
        "fhlmc":  "freddie mac",
        "heloc":  "home equity line of credit",
        "gfe":    "good faith estimate",
        "cd":     "closing disclosure",
        "le":     "loan estimate",
    },
    "insurance": {
        "doi":    "department of insurance",
        "e&o":    "errors and omissions",
        "gl":     "general liability",
        "wc":     "workers compensation",
        "coi":    "certificate of insurance",
        "dec":    "declarations page",
        "aob":    "assignment of benefits",
        "uwi":    "underwriting information",
        "clue":   "comprehensive loss underwriting exchange",
        "pip":    "personal injury protection",
    },
    "therapist": {
        "dap":    "data assessment plan",
        "soap":   "subjective objective assessment plan",
        "hipaa":  "health insurance portability and accountability act",
        "phi":    "protected health information",
        "dx":     "diagnosis",
        "tx":     "treatment",
        "iop":    "intensive outpatient program",
        "php":    "partial hospitalization program",
        "cbt":    "cognitive behavioral therapy",
        "dbt":    "dialectical behavior therapy",
        "emdr":   "eye movement desensitization reprocessing",
    },
    "chiropractor": {
        "soap":   "subjective objective assessment plan",
        "rom":    "range of motion",
        "pi":     "personal injury",
        "hipaa":  "health insurance portability and accountability act",
        "icd":    "international classification of diseases",
        "cpt":    "current procedural terminology",
        "eob":    "explanation of benefits",
    },
    "dentist": {
        "hipaa":  "health insurance portability and accountability act",
        "cddt":   "current dental terminology",
        "perio":  "periodontal",
        "ortho":  "orthodontic",
        "endo":   "endodontic",
        "eob":    "explanation of benefits",
        "pano":   "panoramic radiograph",
    },
    "teacher": {
        "iep":    "individualized education program",
        "504":    "section 504 accommodation plan",
        "ell":    "english language learner",
        "sped":   "special education",
        "pbis":   "positive behavioral interventions and supports",
        "mtss":   "multi-tiered system of supports",
        "rti":    "response to intervention",
        "ferpa":  "family educational rights and privacy act",
        "pd":     "professional development",
        "plc":    "professional learning community",
    },
    "vet": {
        "soap":   "subjective objective assessment plan",
        "avma":   "american veterinary medical association",
        "rx":     "prescription",
        "dx":     "diagnosis",
        "tx":     "treatment",
        "hx":     "history",
        "pe":     "physical examination",
    },
    "electrician": {
        "nec":    "national electrical code",
        "gfci":   "ground fault circuit interrupter",
        "afci":   "arc fault circuit interrupter",
        "atp":    "ampere trip point",
        "rfi":    "request for information",
        "co":     "change order",
        "ntp":    "notice to proceed",
    },
    "plumber": {
        "ipc":    "international plumbing code",
        "upc":    "uniform plumbing code",
        "rfi":    "request for information",
        "co":     "change order",
        "ntp":    "notice to proceed",
        "pex":    "cross-linked polyethylene",
        "abs":    "acrylonitrile butadiene styrene",
    },
    # ── Additional verticals ──────────────────────────────────────────────────
    "marketing": {
        "seo":    "search engine optimization",
        "sem":    "search engine marketing",
        "ppc":    "pay per click",
        "ctr":    "click through rate",
        "cpc":    "cost per click",
        "cpa":    "cost per acquisition",
        "roi":    "return on investment",
        "kpi":    "key performance indicator",
        "crm":    "customer relationship management",
        "cta":    "call to action",
        "b2b":    "business to business",
        "b2c":    "business to consumer",
        "saas":   "software as a service",
        "mrr":    "monthly recurring revenue",
        "arr":    "annual recurring revenue",
    },
    "pastor": {
        "vbs":    "vacation bible school",
        "awana":  "approved workmen are not ashamed",
        "acl":    "adult community life",
        "lcm":    "leadership core meeting",
        "sml":    "small group leader",
    },
    "salon": {
        "pbe":    "professional beauty equipment",
        "cosmo":  "cosmetology",
        "esti":   "esthetician",
        "nail":   "nail technician",
        "hsc":    "hair salon coordinator",
    },
    "travelagent": {
        "gds":    "global distribution system",
        "iata":   "international air transport association",
        "fam":    "familiarization trip",
        "fx":     "foreign exchange",
        "ota":    "online travel agency",
        "pnr":    "passenger name record",
        "roi":    "return on investment",
    },
    "restaurant": {
        "cogs":   "cost of goods sold",
        "foh":    "front of house",
        "boh":    "back of house",
        "pos":    "point of sale",
        "haccp":  "hazard analysis critical control points",
        "fifo":   "first in first out",
        "eighty six": "item unavailable",
    },
    "landlord": {
        "noi":    "net operating income",
        "cap":    "capitalization rate",
        "roi":    "return on investment",
        "hoa":    "homeowners association",
        "sec dep": "security deposit",
        "ltv":    "loan to value",
    },
    "principal": {
        "iep":    "individualized education program",
        "504":    "section 504 accommodation plan",
        "pbis":   "positive behavioral interventions and supports",
        "mtss":   "multi-tiered system of supports",
        "ferpa":  "family educational rights and privacy act",
        "sped":   "special education",
        "ell":    "english language learner",
        "plc":    "professional learning community",
    },
    "mortuary": {
        "fda":    "food and drug administration",
        "ftc":    "federal trade commission",
        "osha":   "occupational safety and health administration",
        "dna":    "do not autopsy",
        "dnr":    "do not resuscitate",
    },
    "eventplanner": {
        "rsvp":   "repondez sil vous plait",
        "av":     "audio visual",
        "beo":    "banquet event order",
        "rfp":    "request for proposal",
        "roi":    "return on investment",
        "f&b":    "food and beverage",
    },
    "church": {
        "vbs":    "vacation bible school",
        "awana":  "approved workmen are not ashamed",
        "501c3":  "nonprofit tax exempt status",
        "aed":    "automated external defibrillator",
        "acl":    "adult community life",
    },
    "personaltrainer": {
        "rm":     "repetition maximum",
        "hiit":   "high intensity interval training",
        "bmr":    "basal metabolic rate",
        "tdee":   "total daily energy expenditure",
        "bmi":    "body mass index",
        "rom":    "range of motion",
        "par q":  "physical activity readiness questionnaire",
    },
    "designer": {
        "ui":     "user interface",
        "ux":     "user experience",
        "rgb":    "red green blue",
        "cmyk":   "cyan magenta yellow key",
        "dpi":    "dots per inch",
        "ppi":    "pixels per inch",
        "svg":    "scalable vector graphics",
        "sow":    "scope of work",
    },
    "militaryspouse": {
        "pcs":    "permanent change of station",
        "tdy":    "temporary duty assignment",
        "bah":    "basic allowance for housing",
        "bas":    "basic allowance for subsistence",
        "deers":  "defense enrollment eligibility reporting system",
        "tricare":"military health insurance",
        "id card":"military dependent identification",
    },
    "funeral": {
        "ftc":    "federal trade commission",
        "fda":    "food and drug administration",
        "osha":   "occupational safety and health administration",
        "dnr":    "do not resuscitate",
        "cremains":"cremated remains",
    },
    "nutritionist": {
        "bmi":    "body mass index",
        "bmr":    "basal metabolic rate",
        "tdee":   "total daily energy expenditure",
        "gi":     "glycemic index",
        "gl":     "glycemic load",
        "dri":    "dietary reference intake",
        "rda":    "recommended dietary allowance",
        "ibw":    "ideal body weight",
    },
}

# Default empty map for verticals without specific abbreviations
_DEFAULT_ABBREVS = {}

# DB-loaded abbreviations (fetched from /v1/abbreviations at startup)
_abbrevs_db: dict | None = None
_abbrevs_db_ts: float = 0.0
_abbrevs_db_product: str | None = None


# ── Cache configuration ────────────────────────────────────────────────────────
CACHE_TTL      = 600   # 10 minutes
ERROR_COOLDOWN = 30    # retry after failure

# Vertical metadata (loaded once at startup via GET /v1/me)
_vertical = None

# Skills cache
_skills_cache         = None
_skills_cache_ts      = 0.0
_skills_cache_err_until = 0.0

# Triggers cache — {skill_id: [phrase, ...]}
_triggers_cache           = None
_triggers_cache_ts        = 0.0
_triggers_cache_err_until = 0.0


async def api_get(path):
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{API_BASE}{path}",
            headers={**AUTH_HEADERS, "X-Product-ID": (_vertical or {}).get("product_id", "law")}
        )
        resp.raise_for_status()
        return resp.json()


async def load_vertical():
    """Fetch vertical metadata from /v1/me on startup. Falls back to farmer."""
    global _vertical
    try:
        path = f"/v1/me?product_id={PRODUCT_ID}" if PRODUCT_ID else "/v1/me"
        _vertical = await api_get(path)
    except Exception:
        # Fallback: derive from license key prefix client-side
        prefix = LICENSE_KEY.split("_")[0] + "_" if "_" in LICENSE_KEY else "ft_"
        _vertical = {
            "product_id":   "farmer",
            "product_name": "FarmerTasksAI",
            "display_name": "FarmerTasksAI",
            "tool_prefix":  "farmertasksai",
            "occupation":   "farmer",
            "support_email":"support@farmertasksai.com",
            "domain":       "farmertasksai.com",
        }
    return _vertical


async def load_abbreviations():
    """
    Fetch abbreviations for this vertical from GET /v1/abbreviations.
    Populates _abbrevs_db. Falls back silently to _ABBREVS_FALLBACK if unavailable.
    Called once at startup after load_vertical().
    """
    global _abbrevs_db, _abbrevs_db_ts, _abbrevs_db_product
    try:
        data = await api_get("/v1/abbreviations")
        _abbrevs_db = data.get("abbreviations", {})
        _abbrevs_db_product = data.get("product_id")
        _abbrevs_db_ts = time.monotonic()
    except Exception:
        # Non-fatal: _ABBREVS_FALLBACK will be used instead
        _abbrevs_db = None
    return _abbrevs_db


async def get_skills():
    global _skills_cache, _skills_cache_ts, _skills_cache_err_until
    now = time.monotonic()
    if _skills_cache is not None and (now - _skills_cache_ts) < CACHE_TTL:
        return _skills_cache
    if now < _skills_cache_err_until:
        return _skills_cache if _skills_cache is not None else []
    try:
        _skills_cache = await api_get("/v1/skills")
        _skills_cache_ts = now
        _skills_cache_err_until = 0.0
    except Exception:
        _skills_cache_err_until = now + ERROR_COOLDOWN
        if _skills_cache is None:
            _skills_cache = []
    return _skills_cache


async def get_triggers():
    """Return trigger phrases {skill_id: [phrase, ...]}. Fails silently."""
    global _triggers_cache, _triggers_cache_ts, _triggers_cache_err_until
    now = time.monotonic()
    if _triggers_cache is not None and (now - _triggers_cache_ts) < CACHE_TTL:
        return _triggers_cache
    if now < _triggers_cache_err_until:
        return _triggers_cache if _triggers_cache is not None else {}
    try:
        raw = await api_get("/v1/skills/triggers")
        _triggers_cache = {
            sid: [p.lower() for p in v.get("triggers", [])]
            for sid, v in raw.items()
        }
        _triggers_cache_ts = now
        _triggers_cache_err_until = 0.0
    except Exception:
        _triggers_cache_err_until = now + ERROR_COOLDOWN
        if _triggers_cache is None:
            _triggers_cache = {}
    return _triggers_cache


def expand_query(query, product_id):
    """Expand vertical-specific abbreviations before matching."""
    # Prefer DB-loaded abbreviations; fall back to hardcoded map
    if _abbrevs_db is not None:
        abbrevs = _abbrevs_db
    else:
        abbrevs = _ABBREVS_FALLBACK.get(product_id, _DEFAULT_ABBREVS)
    if not abbrevs:
        return query
    words = query.lower().split()
    expansions = [abbrevs[w.strip(".,;:?!")] for w in words if w.strip(".,;:?!") in abbrevs]
    return (query + " " + " ".join(expansions)).strip() if expansions else query


def _word_in_text(word, text):
    """True if `word` appears as a whole word in `text`."""
    return bool(re.search(r'(?<!\w)' + re.escape(word) + r'(?!\w)', text))


def score_skill(skill, query_lower, query_words, triggers):
    """Three-tier scoring: trigger match (10) > name match (3) > description match (1)."""
    skill_id  = skill.get("id", "")
    name_text = skill.get("name", "").lower()
    desc_text = skill.get("description", "").lower()
    full_text = name_text + " " + desc_text
    # Tier 1 — trigger phrase (whole-word, bidirectional)
    for phrase in triggers.get(skill_id, []):
        if _word_in_text(phrase, query_lower) or _word_in_text(query_lower, phrase):
            return 10
    # Tier 2 — keyword
    return sum(
        3 if _word_in_text(w, name_text) else 1
        for w in query_words
        if _word_in_text(w, full_text)
    )


def build_tools(prefix, product_name, occupation):
    """Build the four MCP tools with vertical-specific names and descriptions."""
    # Build example queries from the top trigger phrases for this vertical
    _examples = {
        "attorney": "e.g. 'statute of limitations', 'motion to compel', 'demand letter', 'deposition prep', 'discovery requests'",
        "realtor": "e.g. 'listing presentation', 'buyer consultation', 'CMA analysis', 'open house checklist'",
        "farmer": "e.g. 'crop insurance claim', 'USDA loan application', 'conservation plan', 'farm succession'",
        "teacher": "e.g. 'IEP meeting', 'lesson plan', 'parent conference', 'classroom management'",
        "therapist": "e.g. 'treatment plan', 'SOAP note', 'intake assessment', 'crisis intervention'",
        "contractor": "e.g. 'change order', 'bid proposal', 'punch list', 'lien waiver'",
        "marketing": "e.g. 'content calendar', 'SEO audit', 'email campaign', 'brand strategy'",
    }
    occ_key = occupation.split(',')[0].strip()
    audience = normalize_audience_label(occ_key)
    domain_adjective = normalize_domain_adjective(occ_key)
    examples = _examples.get(domain_adjective, _examples.get(product_name.replace('TasksAI','').lower().strip(), f"e.g. a {domain_adjective} task"))

    return [
        Tool(
            name=f"{prefix}_search",
            description=(
                f"Search {product_name}'s library of interactive guided workflows for {audience}. "
                f"Each workflow walks the user through a structured, multi-step process with intake questions, "
                f"domain-specific checklists, recordkeeping steps, and document generation templates "
                f"that cannot be replicated from general knowledge alone. "
                f"Use this tool whenever the user has a {domain_adjective}-related question or task — "
                f"even simple-sounding requests may have dedicated workflows with practical requirements, "
                f"review points, and fillable templates. "
                f"Returns a numbered list of matching workflows with descriptions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": f"{domain_adjective.title()} topic or task ({examples})"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name=f"{prefix}_execute",
            description=(
                f"Launch a {product_name} guided workflow by its ID. Returns the full interactive framework "
                f"including intake questions, step-by-step instructions, domain-specific guidance, "
                f"and document templates. Costs 1 credit. Use {prefix}_search first to find the workflow ID."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "skill_id": {
                        "type": "string",
                        "description": f"Workflow ID from {prefix}_search results"
                    }
                },
                "required": ["skill_id"]
            }
        ),
        Tool(
            name=f"{prefix}_balance",
            description=f"Check your remaining {product_name} credit balance.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name=f"{prefix}_categories",
            description=(
                f"Browse all {product_name} workflow categories. "
                "Use when the user isn't sure what to search for, "
                "or when a search returns no results."
            ),
            inputSchema={"type": "object", "properties": {}}
        ),
    ]


def normalize_audience_label(label):
    """Return a natural audience phrase without naive pluralization."""
    label = (label or "professionals").strip()
    if label in {"attorney", "lawyer"}:
        return f"{label}s"
    if label == "farmer":
        return "farmers, ranchers, and agricultural operations managers"
    if label in {"legal", "law"}:
        return "legal professionals"
    return label


def normalize_domain_adjective(label):
    """Return a natural adjective for tool descriptions and query labels."""
    label = (label or "professional").strip()
    if label in {"attorneys and legal professionals", "legal professionals", "attorney", "lawyer", "law"}:
        return "legal"
    return label


def build_system_prompt(product_name, occupation, prefix, domain, support_email):
    return f"""You are a {product_name} assistant for {occupation}.

When the user asks any {occupation.split(',')[0]}-related question, call {prefix}_search first to find a matching expert framework. The user is paying for {product_name}'s expert-built frameworks — always search before answering.

Workflow:
1. Call {prefix}_search with the user's question
2. Present the numbered results
3. Let the user choose, then call {prefix}_execute with the skill_id (costs 1 credit)
4. Show remaining credit balance

Rules:
- Always search first, even for simple questions
- Never call {prefix}_execute without user confirmation
- If no results, suggest {prefix}_categories

{domain} | Support: {support_email}"""


# ── Server initialization ──────────────────────────────────────────────────────
# Note: MCP server tools are registered at module load time, but we need
# vertical metadata from the API. We use a two-phase init:
# Phase 1: create server with placeholder tools (farmer defaults)
# Phase 2: on first tool call, ensure vertical is loaded and tools are current

# Placeholder system prompt (overwritten after /v1/me loads)
_system_prompt_text = build_system_prompt(
    "FarmerTasksAI", "farmers, ranchers, and agricultural operations managers",
    "farmertasksai", "farmertasksai.com", "support@farmertasksai.com"
)

# NOTE: Do NOT pass instructions= here. Testing showed that Claude Desktop
# v1.9+ ignores or deprioritizes MCP server instructions. The working March
# config had no instructions and no prompts — just clean tool descriptions.
server = Server("farmertasksai")

# Placeholder tools using farmer defaults (overwritten after /v1/me loads)
_tools = build_tools("farmertasksai", "FarmerTasksAI", "farmer")

# NOTE: Prompts capability intentionally removed. The working March 2026
# config had no prompts — just tools. Adding prompts may cause Claude Desktop
# to deprioritize tool auto-invocation.


@server.list_tools()
async def list_tools():
    # Ensure vertical is loaded before advertising tools
    if _vertical is None:
        await load_vertical()
        await load_abbreviations()
        _rebuild_tools()
    return _tools


def _rebuild_tools():
    """Rebuild tools and system prompt once vertical metadata is available."""
    global _tools, _system_prompt_text
    if _vertical is None:
        return
    prefix   = _vertical.get("tool_prefix", "farmertasksai")
    name     = _vertical.get("product_name", "FarmerTasksAI")
    occ      = _vertical.get("occupation", "professionals")
    domain   = _vertical.get("domain", "farmertasksai.com")
    support  = _vertical.get("support_email", "support@farmertasksai.com")
    _tools = build_tools(prefix, name, occ)
    _system_prompt_text = build_system_prompt(name, occ, prefix, domain, support)


@server.call_tool()
async def call_tool(name, arguments):
    # Ensure vertical loaded on first tool call
    if _vertical is None:
        await load_vertical()
        await load_abbreviations()
        _rebuild_tools()

    v          = _vertical or {}
    prefix     = v.get("tool_prefix", "farmertasksai")
    product_id = v.get("product_id", "farmer")
    product_name = v.get("product_name", "FarmerTasksAI")
    occupation   = v.get("occupation", "professionals")

    try:
        # ── Search ────────────────────────────────────────────────────────────
        if name == f"{prefix}_search":
            skills, triggers = await get_skills(), await get_triggers()
            query        = expand_query(arguments.get("query", ""), product_id)
            query_lower  = query.lower()
            STOP_WORDS   = {"a","an","the","and","or","of","in","to","for","is","are",
                            "with","at","by","on","from","as","it","its","be","was","can"}
            raw_words    = query.split()
            query_words  = [
                w_lower for w_orig, w_lower in zip(raw_words, query_lower.split())
                if w_lower not in STOP_WORDS and (len(w_lower) > 2 or w_orig.isupper())
            ]
            scored = [(score_skill(s, query_lower, query_words, triggers), s) for s in skills]
            scored = [(sc, s) for sc, s in scored if sc > 0]
            scored.sort(key=lambda x: -x[0])
            matches = [s for _, s in scored[:5]]

            if not matches:
                return [TextContent(type="text", text=(
                    f"No skills found matching **'{arguments.get('query', '')}'**.\n\n"
                    "**Suggestions:**\n"
                    "- Try different keywords or a more specific phrase\n"
                    f"- Use `{prefix}_categories` to browse all skill categories\n"
                    "- Ask the user to rephrase their request\n\n"
                    f"**DO NOT call `{prefix}_execute`** — no skill has been selected."
                ))]

            lines = [f"**{len(matches)} skills found for '{arguments.get('query', '')}':**\n"]
            for i, s in enumerate(matches, 1):
                desc = s.get("description", "")[:100]
                lines.append(f"{i}. **{s['name']}** (`{s['id']}`)\n   {desc}\n")

            lines.append("---")
            lines.append(
                "**\U0001f6d1 REQUIRED \u2014 DO NOT SKIP:**\n"
                "Present the numbered list above to the user EXACTLY as shown. "
                "Then ask: *\"Which of these best fits your situation? "
                "(Reply with a number, or describe your task differently and I'll search again.)\"*\n\n"
                f"**DO NOT call `{prefix}_execute` until the user replies with their choice. "
                "Each execution costs 1 credit and cannot be undone.**"
            )
            return [TextContent(type="text", text="\n".join(lines))]

        # ── Execute ───────────────────────────────────────────────────────────
        elif name == f"{prefix}_execute":
            skill_id = arguments.get("skill_id", "")
            if not skill_id:
                return [TextContent(type="text", text="Error: skill_id is required.")]

            result = await api_get(f"/v1/skills/{skill_id}/execute")

            content = result.get("schema", result.get("content", ""))
            skill_name = result.get("skill_name", skill_id)
            credits_remaining = result.get("credits_remaining", "?")

            return [TextContent(type="text", text=(
                f"# {skill_name}\n\n"
                f"{content}\n\n"
                f"---\n*Credits remaining: {credits_remaining}*"
            ))]

        # ── Balance ───────────────────────────────────────────────────────────
        elif name == f"{prefix}_balance":
            result = await api_get("/v1/credits/balance")
            balance  = result.get("credits_balance", "?")
            lic_type = result.get("license_type", "")
            domain   = v.get("domain", "farmertasksai.com")
            return [TextContent(type="text", text=(
                f"**{product_name} Credits**\n\n"
                f"- Balance: **{balance} credits**\n"
                f"- License type: {lic_type}\n"
                f"- MCP server version: {SERVER_VERSION}\n\n"
                f"Purchase more at: https://{domain}/#pricing"
            ))]

        # ── Categories ────────────────────────────────────────────────────────
        elif name == f"{prefix}_categories":
            skills = await get_skills()
            cats: dict[str, int] = {}
            for s in skills:
                cat = s.get("category_id") or s.get("category", "General")
                cats[cat] = cats.get(cat, 0) + 1
            cats_sorted = sorted(cats.items(), key=lambda x: -x[1])
            lines = [f"**{product_name} Skill Categories** ({len(skills)} total skills)\n"]
            for cat, count in cats_sorted:
                lines.append(f"- **{cat}** ({count} skills)")
            lines.append(f"\nSearch within any category using `{prefix}_search`.")
            return [TextContent(type="text", text="\n".join(lines))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 402:
            domain = v.get("domain", "farmertasksai.com")
            return [TextContent(type="text", text=(
                f"**Insufficient credits.**\n\n"
                f"Purchase more at: https://{domain}/#pricing"
            ))]
        elif e.response.status_code == 401:
            return [TextContent(type="text", text=(
                "**Invalid or expired license key.**\n\n"
                "Check your purchase confirmation email or contact support."
            ))]
        return [TextContent(type="text", text=f"API error: {e.response.status_code}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def _ping_first_connection():
    """Fire-and-forget: tell the API this license just connected for the first time."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.get(
                f"{API_BASE}/track/first-connection",
                params={"license_key": LICENSE_KEY}
            )
    except Exception:
        pass  # non-fatal — never block startup


async def main():
    # Load vertical metadata + abbreviations before accepting connections
    await load_vertical()
    await load_abbreviations()
    _rebuild_tools()

    # Ping first-connection tracker (idempotent — API only records it once)
    asyncio.create_task(_ping_first_connection())

    v = _vertical or {}
    abbrev_count = len(_abbrevs_db) if _abbrevs_db is not None else 0
    abbrev_src   = "db" if _abbrevs_db is not None else "fallback"
    # MCP uses stdout for JSON-RPC — all logging MUST go to stderr
    import sys as _sys
    print(f"[OK] {v.get('product_name', 'TasksAI')} MCP Server ready (v{SERVER_VERSION})", file=_sys.stderr, flush=True)
    print(f"     Abbreviations: {abbrev_count} loaded from {abbrev_src}", file=_sys.stderr, flush=True)
    print(f"     Vertical: {v.get('product_id', 'unknown')} | "
          f"Tools: {v.get('tool_prefix', 'tasksai')}_search / execute / balance / categories",
          file=_sys.stderr, flush=True)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
