"""CLAUDE.md hard rules, checked in code: the LLM never decides compliance, no real-looking personal data, no keys."""
import ast
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import llm
from app.llm import DocumentExtraction
from app.main import app

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent
APP = BACKEND / "app"


def _module_imports(path: Path) -> set[str]:
    """app.* modules imported by one file (relative imports resolved)."""
    pkg = ("app." + ".".join(path.relative_to(APP).with_suffix("").parts)).removesuffix(".__init__")
    base = pkg.split(".") if path.name == "__init__.py" else pkg.split(".")[:-1]
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            mod = ".".join(base[: len(base) - node.level + 1] + ([node.module] if node.module else [])) if node.level else node.module
            if mod and mod.startswith("app"):
                out.add(mod)
                out.update(f"{mod}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names if a.name.startswith("app"))
    return out


def _reachable(start: str) -> set[str]:
    files = {("app." + ".".join(p.relative_to(APP).with_suffix("").parts)).removesuffix(".__init__"): p for p in APP.rglob("*.py")}
    seen, todo = set(), [start]
    while todo:
        mod = todo.pop()
        if mod in seen or mod not in files:
            continue
        seen.add(mod)
        todo.extend(_module_imports(files[mod]))
    return seen


def test_only_reactivate_qr_sets_live():
    setters = []
    for p in APP.rglob("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            for node in ast.walk(fn):
                if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == "qr_status" for t in node.targets)
                        and isinstance(node.value, ast.Constant) and node.value.value == "LIVE"):
                    setters.append(f"{p.relative_to(BACKEND)}::{fn.name}")
    assert setters == ["app\\tools\\compliance.py::reactivate_qr"] or setters == ["app/tools/compliance.py::reactivate_qr"]


def test_compliance_code_cannot_reach_the_llm():
    for start in ("app.rules_engine", "app.tools.compliance", "app.scoring"):
        assert "app.llm" not in _reachable(start), f"{start} imports the LLM (directly or indirectly)"


def test_a_lying_vision_model_cannot_get_a_blurry_pan_accepted(monkeypatch):
    """Even if the LLM claims a blurry photo is a perfect, verified PAN, the local checks reject it."""
    monkeypatch.setattr(llm, "extract_document", lambda *a, **k: DocumentExtraction(
        doc_type="PAN", name="RAMESH SHARMA", id_number="ABCZS1234K", readable=True, issues=[], confidence=1.0))
    with TestClient(app) as c:
        c.post("/api/demo/reset")
        c.post("/api/journeys/M0001/start")
        with open(BACKEND / "demo_assets" / "pan_blurry.jpg", "rb") as f:
            v = c.post("/api/journeys/M0001/upload", files={"file": ("p.jpg", f)}, data={"doc_type": "PAN"}).json()
        assert v["state"]["last_check"]["decision"] == "REJECTED" and v["state"]["last_check"]["reason_code"] == "BLURRY"
        assert c.get("/api/merchants/M0001/compliance").json()["compliant"] is False
        c.post("/api/demo/reset")


def _text_files():
    skip = {"node_modules", "venv", "dist", ".pytest_cache", "__pycache__", "data", "demo_assets", "screenshots", ".git"}
    for p in ROOT.rglob("*"):
        if p.is_file() and not skip & set(p.parts) and p.suffix in {".py", ".ts", ".tsx", ".md", ".yaml", ".json", ".html", ".sh", ".example"}:
            if p.name != "package-lock.json":
                yield p


def test_no_issuable_pan_numbers_anywhere():
    # A real PAN's 4th character is the holder type; ours uses Z, which is never issued.
    issuable = re.compile(r"\b[A-Z]{3}[ABCFGHLJPT][A-Z][0-9]{4}[A-Z]\b")
    hits = [f"{p.relative_to(ROOT)}: {m}" for p in _text_files() for m in issuable.findall(p.read_text(encoding="utf-8", errors="ignore"))]
    assert hits == []


def test_no_api_keys_in_the_repository():
    key = re.compile(r"AIza[0-9A-Za-z_-]{30,}|sk-[A-Za-z0-9]{32,}|api[-_]?key['\"]?\s*[:=]\s*['\"][A-Za-z0-9_-]{20,}['\"]", re.I)
    assert [str(p.relative_to(ROOT)) for p in _text_files() if key.search(p.read_text(encoding="utf-8", errors="ignore"))] == []


def test_synthetic_names_avoid_public_figures():
    from scripts.seed import PUBLIC_FIGURE_NAMES, generate
    merchants, employees = generate()
    names = {m.owner_name for m in merchants} | {e.name for e in employees}
    assert not names & set(PUBLIC_FIGURE_NAMES)
