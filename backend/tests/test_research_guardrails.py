"""Research and the future chatbot read md through ReadSession only, and it cannot write."""
import ast
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.md.database import _read_only_engine

BACKEND = Path(__file__).resolve().parent.parent
RESEARCH_MODULES = (
    "app/md/performance.py",
    "app/md/insights.py",
    "app/api/routes/research.py",
)
FORBIDDEN = {"MdSession", "SessionLocal", "get_db", "engine"}


def test_a_read_only_session_refuses_a_write(tmp_path):
    path = tmp_path / "md.db"
    owner = create_engine(f"sqlite:///{path}")
    with owner.begin() as c:
        c.execute(text("create table sector (code text)"))
        c.execute(text("insert into sector values ('IT')"))
    reader = sessionmaker(bind=_read_only_engine(f"sqlite:///{path}"))()
    assert reader.execute(text("select count(*) from sector")).scalar() == 1
    with pytest.raises(OperationalError):
        reader.execute(text("insert into sector values ('ZZ')"))
        reader.commit()
    reader.close()


def test_research_code_never_opens_a_writable_session():
    wrong = []
    for relative in RESEARCH_MODULES:
        path = BACKEND / relative
        if not path.exists():
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            name = None
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.alias):
                name = node.asname or node.name.split(".")[-1]
            if name in FORBIDDEN:
                wrong.append(f"{relative}: {name}")
    assert wrong == []


def test_research_reads_go_through_read_session_only():
    source = (BACKEND / "app/md/read.py").read_text()
    research = source[source.index("# -- research: read-only") :]
    tree = ast.parse(research)
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert functions, "the research section is empty"
    for function in functions:
        body = ast.unparse(function)
        if function.name == "_read":
            assert "ReadSession()" in body and "MdSession" not in body
            continue
        assert "_read()" in body, f"{function.name} must read through _read()"
        assert "_session(" not in body and "MdSession" not in body, function.name
