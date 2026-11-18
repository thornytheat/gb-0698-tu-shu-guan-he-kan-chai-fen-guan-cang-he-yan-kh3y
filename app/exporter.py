import csv
import io
import json


def _row(run, kind, line="", reason="", payload=None):
    return [
        run["id"],
        run["digest"],
        run["rule_version"],
        kind,
        line,
        reason,
        json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
    ]


def evidence_csv(run):
    """唯一证据 CSV：年度缺口与每期原始刊名可同时核对。"""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["run_id", "sha256", "rule_version", "kind", "line", "reason", "evidence"])
    result = run["result"]
    writer.writerow(
        _row(
            run,
            "manifest",
            payload={
                "balance": result["balance"],
                "decision": run["decision"],
                "revision": run["revision"],
                "blocked": result.get("blocked", False),
                "resume": result.get("resume", {}),
            },
        )
    )
    for chain in result.get("chains", []):
        writer.writerow(
            _row(
                run,
                "chain",
                payload={
                    "chain_key": chain["chain_key"],
                    "year": chain["year"],
                    "volume": chain["volume"],
                    "issn": chain["issn"],
                    "journal_keys": chain["journal_keys"],
                    "title": chain["title"],
                    "confirmed": chain.get("confirmed", False),
                    "missing": (
                        chain.get("confirmed_missing", [])
                        if chain.get("confirmed")
                        else chain.get("missing", [])
                    ),
                    "confirmed_missing": chain.get("confirmed_missing", []),
                    "observed_missing": chain.get("missing", []),
                    "new_missing": chain.get("new_missing", []),
                    "late_issues": chain.get("late_issues", []),
                    "covered": chain["covered"],
                    "suspended": chain["suspended"],
                    "titles": chain["titles"],
                    "record_ids": chain["record_ids"],
                },
            )
        )
        for entry in chain["issues"]:
            writer.writerow(
                _row(
                    run,
                    "issue",
                    line=(entry["records"][0]["line"] if entry["records"] else ""),
                    reason=entry["status"],
                    payload={
                        "chain_key": chain["chain_key"],
                        "year": chain["year"],
                        "volume": chain["volume"],
                        "issue": entry["issue"],
                        # 当期原始刊名：旧刊与改名后的新刊各自保留。
                        "issue_title": entry["title"],
                        "issue_title_source": entry.get("title_source", ""),
                        "issue_titles": entry["titles"],
                        "issn": entry["issn"],
                        "canonical": entry["canonical"],
                        "status": entry["status"],
                        "binding": entry["binding"],
                        "bindings": entry["bindings"],
                        "copy": entry["copy"],
                        "record_ids": entry["record_ids"],
                        "records": entry["records"],
                    },
                )
            )
    for record in result.get("late", []):
        writer.writerow(
            _row(
                run,
                "late",
                line=record.get("line", ""),
                reason="LATE_RECORD",
                payload=record,
            )
        )
    for conflict in result.get("title_conflicts", []):
        writer.writerow(_row(run, "title_conflict", reason=conflict["reason"], payload=conflict))
    for conflict in result.get("binding_conflicts", []):
        writer.writerow(_row(run, "binding_conflict", reason=conflict["reason"], payload=conflict))
    for row in result.get("final", []):
        writer.writerow(
            _row(run, "result", line=row.get("line", ""), reason=row.get("status", ""), payload=row)
        )
    for row in result.get("quarantine", []):
        writer.writerow(
            _row(
                run,
                "quarantine",
                line=row.get("line", ""),
                reason=row["reason"],
                payload=row,
            )
        )
    return "﻿" + out.getvalue()
