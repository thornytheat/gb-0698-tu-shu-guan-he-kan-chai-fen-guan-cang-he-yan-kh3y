import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from app.config import DATA_DIR, RULE_VERSION
from app.errors import BusinessError


def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA_DIR / "runs.sqlite", timeout=15)
    db.row_factory = sqlite3.Row
    db.execute(
        "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, decision TEXT NOT NULL DEFAULT '待复核', created TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS checkpoints (digest TEXT NOT NULL, year TEXT NOT NULL, payload TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY (digest, year))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS confirmed_chains (chain_key TEXT PRIMARY KEY, year TEXT NOT NULL, volume TEXT NOT NULL, issns TEXT NOT NULL, title TEXT NOT NULL, missing TEXT NOT NULL, covered TEXT NOT NULL, suspended TEXT NOT NULL, run_id TEXT NOT NULL, created TEXT NOT NULL)"
    )
    return db


def digest_for(text):
    return hashlib.sha256((RULE_VERSION + "\n" + text).encode()).hexdigest()


def save(text, result):
    digest = digest_for(text)
    ident = digest[:16]
    with connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO runs(id,digest,result,created) VALUES(?,?,?,?)",
            (
                ident,
                digest,
                json.dumps(dict(result, rule_version=RULE_VERSION), ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return get(ident)


def get(ident):
    with connect() as db:
        row = db.execute("SELECT * FROM runs WHERE id=?", (ident,)).fetchone()
    if row is None:
        raise BusinessError("NOT_FOUND", "批次不存在", 404)
    item = dict(row)
    item["result"] = json.loads(item["result"])
    item["rule_version"] = item["result"].get("rule_version", "2026.11.18.1")
    return item


def _peek(ident):
    with connect() as db:
        row = db.execute("SELECT * FROM runs WHERE id=?", (ident,)).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["result"] = json.loads(item["result"])
    item["rule_version"] = item["result"].get("rule_version", "2026.11.18.1")
    return item


def execute(text):
    """计算并持久化；已完成的年度从检查点恢复，晚到记录不越过已确认缺口。

    批次按规则版与输入摘要唯一确定。若既有批次仍有待续算年度（上次核验
    中断），则按检查点续算并更新该批次；已完成批次保持原证据不变。
    """
    from app.pipeline import run

    digest = digest_for(text)
    ident = digest[:16]
    existing = _peek(ident)
    resume = existing["result"].get("resume", {}) if existing else {}
    if existing is not None and not resume.get("pending_years"):
        return existing

    result = run(
        text,
        resume={
            "read_year": lambda year: load_checkpoint(digest, year),
            "write_year": lambda year, payload: save_checkpoint(digest, year, payload),
        },
        confirmed=confirmed_snapshots(),
    )
    if existing is None:
        saved = save(text, result)
        if not result.get("resume", {}).get("pending_years"):
            clear_checkpoints(digest)
        return saved
    with connect() as db:
        db.execute(
            "UPDATE runs SET result=? WHERE id=?",
            (json.dumps(dict(result, rule_version=RULE_VERSION), ensure_ascii=False), ident),
        )
    if not result.get("resume", {}).get("pending_years"):
        clear_checkpoints(digest)
    return get(ident)


def history():
    with connect() as db:
        return [
            dict(r)
            for r in db.execute(
                "SELECT id,revision,decision,created FROM runs ORDER BY created DESC LIMIT 40"
            )
        ]


def load_checkpoint(digest, year):
    with connect() as db:
        row = db.execute(
            "SELECT payload FROM checkpoints WHERE digest=? AND year=?", (digest, str(year))
        ).fetchone()
    return json.loads(row["payload"]) if row else None


def save_checkpoint(digest, year, payload):
    with connect() as db:
        db.execute(
            "INSERT OR REPLACE INTO checkpoints(digest,year,payload,created) VALUES(?,?,?,?)",
            (
                digest,
                str(year),
                json.dumps(payload, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def clear_checkpoints(digest):
    with connect() as db:
        db.execute("DELETE FROM checkpoints WHERE digest=?", (digest,))


def confirmed_snapshots():
    with connect() as db:
        rows = db.execute("SELECT * FROM confirmed_chains ORDER BY year, volume").fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["issns"] = json.loads(item["issns"])
        item["missing"] = json.loads(item["missing"])
        item["covered"] = json.loads(item["covered"])
        item["suspended"] = json.loads(item["suspended"])
        out.append(item)
    return out


def confirm_chains(ident, chains):
    """归档复核时冻结每个年度链的缺口；已确认的同年度链不再被改写。"""
    from app.succession import match_confirmed

    stamp = datetime.now(timezone.utc).isoformat()
    existing = confirmed_snapshots()
    with connect() as db:
        for chain in chains:
            # 同一批次已携带早先确认的缺口，或该年度已被冻结：保持原快照。
            if chain.get("confirmed") or match_confirmed(chain, existing):
                continue
            db.execute(
                "INSERT OR IGNORE INTO confirmed_chains(chain_key,year,volume,issns,title,missing,covered,suspended,run_id,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    chain["chain_key"],
                    str(chain["year"]),
                    str(chain["volume"]),
                    json.dumps(sorted(set(chain.get("journal_keys") or [chain.get("issn", "")]))),
                    chain["title"],
                    json.dumps(chain["missing"]),
                    json.dumps(chain["covered"]),
                    json.dumps(chain["suspended"]),
                    ident,
                    stamp,
                ),
            )


def review(ident, revision, decision):
    if not isinstance(decision, str) or decision not in {"通过", "退回"}:
        raise BusinessError("DECISION", "复核决定无效")
    current = get(ident)
    if decision == "通过" and current["result"].get("blocked"):
        raise BusinessError("BLOCKED", "存在阻断项，请先修正数据", 409)
    with connect() as db:
        changed = db.execute(
            "UPDATE runs SET revision=revision+1,decision=? WHERE id=? AND revision=?",
            (decision, ident, revision),
        ).rowcount
        if not changed:
            raise BusinessError("STALE", "版本已更新，请刷新", 409)
    if decision == "通过":
        confirm_chains(ident, current["result"].get("chains", []))
    return get(ident)
