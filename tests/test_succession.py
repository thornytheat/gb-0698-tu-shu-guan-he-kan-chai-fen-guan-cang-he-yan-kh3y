from app.pipeline import run
from app import store
from app.exporter import evidence_csv
from app.succession import build_chains
import pytest


@pytest.fixture(autouse=True)
def clean_store():
    """每个用例使用独立的批次与已确认缺口库，避免年度链快照互相影响。"""
    from app.config import DATA_DIR

    for name in ("runs.sqlite",):
        path = DATA_DIR / name
        if path.exists():
            path.unlink()
    yield


def series(year, old_title, new_title, old_issn="1000-0300", new_issn="1000-0300",
           old_issues=range(1, 7), new_issues=range(7, 13), volume="005"):
    """构造同卷号内前半年旧刊、后半年新刊的记录行。"""
    rows = ["record_id,title,issn,year,volume,issue,copy,binding,status,note"]
    for n, issue in enumerate(old_issues, 1):
        rows.append(
            f"{year}O{n:02d},{old_title},{old_issn},{year},{volume},{issue},01,"
            f"{year}OB{issue},held,上半年旧刊"
        )
    for n, issue in enumerate(new_issues, 1):
        rows.append(
            f"{year}N{n:02d},{new_title},{new_issn},{year},{volume},{issue},01,"
            f"{year}NB{issue},held,下半年新刊"
        )
    return "\n".join(rows) + "\n"


# TRAP-31 刊名年中更换：同一卷号、刊名不同
def test_succession_single_chain(sample):
    r = run(series("2026", "数据工程", "智能制造"))
    assert len(r["gaps"]) == 1
    assert len(r["chains"]) == 1


def test_succession_keeps_per_issue_title(sample):
    r = run(series("2026", "数据工程", "智能制造"))
    chain = r["chains"][0]
    titles = {entry["issue"]: entry["title"] for entry in chain["issues"][:12]}
    assert titles["1"] == "数据工程"
    assert titles["6"] == "数据工程"
    assert titles["7"] == "智能制造"
    assert titles["12"] == "智能制造"


def test_succession_versions_bounded():
    r = run(series("2026", "数据工程", "智能制造"))
    versions = r["chains"][0]["titles"]
    assert [(v["title"], v["from_issue"], v["to_issue"]) for v in versions] == [
        ("数据工程", "1", "6"),
        ("智能制造", "7", "12"),
    ]


def test_succession_no_gap_when_combined():
    r = run(series("2026", "数据工程", "智能制造"))
    assert r["gaps"][0]["missing"] == []
    assert r["final"] == []


def test_succession_no_duplicate_supplement():
    # 只看新刊名会漏掉旧刊覆盖，按两个刊名分别核验又会重复生成补录。
    partial = series("2026", "数据工程", "智能制造", old_issues=range(1, 5),
                     new_issues=range(7, 13))
    r = run(partial)
    assert len(r["gaps"]) == 1
    keys = [(t["issn"], t["year"], t["issue"]) for t in r["final"]]
    assert len(keys) == len(set(keys))
    assert {t["issue"] for t in r["final"]} == {"5", "6"}


def test_succession_old_title_has_gap():
    # 旧刊覆盖 1-6 期，只用新刊名核算会漏掉这半年的缺口。
    partial = series("2026", "数据工程", "智能制造", old_issues=range(1, 3),
                     new_issues=range(7, 13))
    r = run(partial)
    assert {t["issue"] for t in r["final"]} == {"3", "4", "5", "6"}
    assert all(t["title"] == "数据工程" for t in r["final"])


def test_succession_independent_same_volume():
    # 同卷号但期次都从 1 起算，是独立刊物，不应并链。
    left = series("2026", "甲刊", "甲刊", old_issues=range(1, 7),
                  new_issues=range(1, 7))
    rows = [line for line in left.splitlines()[1:] if line]
    text = "record_id,title,issn,year,volume,issue,copy,binding,status,note\n" + "\n".join(rows) + "\n"
    text += "\n".join(
        f"Z{n:02d},乙刊,1000-0400,2026,005,{i},01,乙{i},held,独立"
        for n, i in enumerate(range(1, 7), 1)
    ) + "\n"
    r = run(text)
    assert len(r["gaps"]) == 2


def test_succession_conflict_same_copy_same_issue():
    rows = ["record_id,title,issn,year,volume,issue,copy,binding,status,note"]
    rows.append("A1,数据工程,1000-0500,2026,009,3,01,B1,held,旧刊")
    rows.append("A2,智能制造,1000-0500,2026,009,3,01,B2,held,新刊")
    r = run("\n".join(rows) + "\n")
    assert r["blocked"] is True
    assert any(c["reason"] == "TITLE_CONFLICT" for c in r["title_conflicts"])
    assert r["final"] == []


# TRAP-32 晚到旧刊不改写已确认缺口
def test_late_old_issue_keeps_confirmed_gap():
    text = series("2026", "数据工程", "智能制造", old_issues=range(1, 5),
                  new_issues=range(7, 13))
    first = store.execute(text)
    assert {t["issue"] for t in first["result"]["final"]} == {"5", "6"}
    store.review(first["id"], first["revision"], "通过")

    late = text + "L1,数据工程,1000-0300,2026,005,5,01,LB5,held,晚到旧刊\n"
    second = store.execute(late)
    chain = second["result"]["gaps"][0]
    assert chain["confirmed"] is True
    assert chain["missing"] == ["5", "6"]
    assert chain["late_issues"] == ["5"]
    assert second["result"]["late"][0]["issue"] == "5"
    assert {t["issue"] for t in second["result"]["final"]} == {"5", "6"}


def test_late_record_not_in_input_quarantine():
    text = series("2026", "数据工程", "智能制造", old_issues=range(1, 4),
                  new_issues=range(7, 13))
    first = store.execute(text)
    store.review(first["id"], first["revision"], "通过")
    late = text + "L1,数据工程,1000-0300,2026,005,4,01,LB4,held,晚到\n"
    second = store.execute(late)
    assert second["result"]["balance"]["input"] == second["result"]["balance"]["accepted"] + second["result"]["balance"]["quarantined"] + second["result"]["balance"]["blank"]
    assert not [q for q in second["result"]["quarantine"] if q["reason"] == "LATE_RECORD"]


# TRAP-33 中断后从最后完成的年度恢复
def test_resume_from_last_completed_year():
    text = series("2025", "数据工程", "智能制造") + "\n".join(
        series("2026", "数据工程", "智能制造").splitlines()[1:]
    ) + "\n"
    saved = {}

    def read_year(year):
        return saved.get(year)

    def write_year(year, payload):
        saved[year] = payload

    run(text, resume={"read_year": read_year, "write_year": write_year})
    assert sorted(saved) == ["2025", "2026"]

    saved.pop("2026")  # 2025 已完成，2026 在中断处缺失
    r = run(text, resume={"read_year": read_year, "write_year": write_year})
    assert r["resume"]["last_completed_year"] == "2025"
    assert r["resume"]["restored_years"] == ["2025"]
    assert r["resume"]["computed_years"] == ["2026"]
    assert "2026" in saved  # 续算后写回


def test_resume_recomputes_after_gap():
    # 中间年度缺失时，其后年度不能跳过续算，必须从缺口年度重新开始。
    text = (
        series("2025", "数据工程", "智能制造")
        + "\n".join(series("2026", "数据工程", "智能制造").splitlines()[1:])
        + "\n"
    )
    saved = {
        "2025": {"chains": [], "title_conflicts": [], "binding_conflicts": []},
        "2026": {"chains": [], "title_conflicts": [], "binding_conflicts": []},
    }
    r = run(
        text,
        resume={
            "read_year": lambda year: saved.get(year),
            "write_year": lambda year, payload: None,
        },
    )
    # 2025 已恢复；2026 已存在检查点，因此两条都能恢复。
    assert r["resume"]["processed_years"] == ["2025", "2026"]


def test_interrupted_batch_resumes_on_resubmit():
    """中断的批次再次提交同一输入时应续算，而不是返回停滞结果。"""
    import json
    from datetime import datetime, timezone
    from app.store import digest_for, connect

    text = series("2026", "数据工程", "智能制造")
    digest = digest_for(text)
    ident = digest[:16]
    stalled = {
        "chains": [],
        "gaps": [],
        "final": [],
        "blocked": False,
        "resume": {"pending_years": ["2026"], "processed_years": []},
        "balance": {"input": 0, "accepted": 0, "quarantined": 0, "blank": 0},
        "quarantine": [],
        "reports": [],
        "reasons": {},
    }
    with connect() as db:
        db.execute(
            "INSERT OR REPLACE INTO runs(id,digest,result,created) VALUES(?,?,?,?)",
            (
                ident,
                digest,
                json.dumps(stalled, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    resumed = store.execute(text)
    assert resumed["id"] == ident
    assert resumed["result"]["resume"]["pending_years"] == []
    assert len(resumed["result"]["gaps"]) == 1
    assert resolved_ok(resumed["result"])


def resolved_ok(result):
    return result["gaps"][0]["missing"] == []


def test_resume_uses_checkpoint_not_recompute():
    text = series("2026", "数据工程", "智能制造")
    saved = {"2026": {"chains": [], "title_conflicts": [], "binding_conflicts": []}}
    written = []

    r = run(
        text,
        resume={
            "read_year": lambda year: saved.get(year),
            "write_year": lambda year, payload: written.append(year),
        },
    )
    assert written == []
    assert r["chains"] == []


def parse_evidence(text):
    import csv
    import io
    import json

    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    for row in rows:
        row["data"] = json.loads(row["evidence"])
    return rows


# 证据导出同时含年度缺口与每期原刊名
def test_export_has_chain_and_issue_titles():
    first = store.execute(series("2026", "数据工程", "智能制造"))
    rows = parse_evidence(evidence_csv(first))
    kinds = {row["kind"] for row in rows}
    assert {"manifest", "chain", "issue"} <= kinds
    chains = [row for row in rows if row["kind"] == "chain"]
    issues = [row for row in rows if row["kind"] == "issue"]
    assert chains[0]["data"]["missing"] == []
    assert chains[0]["data"]["titles"][0]["title"] == "数据工程"
    assert {row["data"]["issue_title"] for row in issues} == {"数据工程", "智能制造"}
    assert all(row["data"]["issue_title"] for row in issues)


def test_export_has_late_kind():
    text = series("2026", "数据工程", "智能制造", old_issues=range(1, 4),
                  new_issues=range(7, 13))
    first = store.execute(text)
    store.review(first["id"], first["revision"], "通过")
    late = text + "L1,数据工程,1000-0300,2026,005,4,01,LB4,held,晚到\n"
    second = store.execute(late)
    rows = parse_evidence(evidence_csv(second))
    late_rows = [row for row in rows if row["kind"] == "late"]
    assert late_rows and late_rows[0]["data"]["issue"] == "4"
    chain = next(row for row in rows if row["kind"] == "chain")["data"]
    assert chain["confirmed_missing"] == ["4", "5", "6"]
    assert chain["late_issues"] == ["4"]


def test_no_purchase_order_output(sample):
    r = run(sample)
    assert not any("采购" in str(k) for k in r)
    assert all("采购" not in str(t) for t in r["final"])
