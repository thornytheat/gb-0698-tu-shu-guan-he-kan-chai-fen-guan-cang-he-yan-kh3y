from collections import defaultdict

from app.errors import BusinessError
from app.report import report
from app.succession import apply_confirmed, build_chains, match_confirmed


def missing(covered, suspended, expected=12):
    return sorted(set(map(str, range(1, expected + 1))) - set(covered) - set(suspended), key=int)


def apply(ctx):
    """按年度逐段核验：每完成一年写检查点，中断后从最后完成的年度继续。

    ctx["read_year"](year) 返回已完成年度的链结果；ctx["write_year"](year, payload)
    持久化本年度结果。ctx["confirmed"] 为已归档的年度缺口快照。
    """
    by_year = defaultdict(list)
    for row in ctx["expanded"]:
        by_year[str(row["year"])].append(row)

    read_year = ctx.get("read_year")
    write_year = ctx.get("write_year")
    confirmed = ctx.get("confirmed") or []

    chains, title_conflicts, binding_conflicts = [], [], []
    restored_years, computed_years, pending_years = [], [], []
    resuming = True  # 只有连续完成的年度前缀可以从检查点恢复

    for index, year in enumerate(sorted(by_year, key=int)):
        restored = read_year(year) if read_year and resuming else None
        if restored is not None:
            year_chains = restored.get("chains", [])
            title_conflicts.extend(restored.get("title_conflicts", []))
            binding_conflicts.extend(restored.get("binding_conflicts", []))
            restored_years.append(year)
        else:
            # 遇到第一个未完成的年度：它就是续算起点，其后年度一并重算。
            resuming = False
            try:
                year_chains, title_bad, binding_bad = build_chains(by_year[year])
            except (BusinessError, ValueError, KeyError, TypeError) as exc:
                # 本年度核验中断：保留此前年度检查点，后续年度等待续算。
                ctx["year_errors"] = ctx.get("year_errors", []) + [
                    {
                        "year": year,
                        "error": getattr(exc, "code", "YEAR_ABORT"),
                        "message": str(exc),
                    }
                ]
                pending_years = sorted(by_year, key=int)[index:]
                break
            title_conflicts.extend(title_bad)
            binding_conflicts.extend(binding_bad)
            if write_year:
                write_year(
                    year,
                    {
                        "chains": year_chains,
                        "title_conflicts": title_bad,
                        "binding_conflicts": binding_bad,
                    },
                )
            computed_years.append(year)
        chains.extend(year_chains)

    for chain in chains:
        apply_confirmed(chain, match_confirmed(chain, confirmed))

    out = []
    for c in chains:
        out.append(
            {
                "chain_key": c["chain_key"],
                "issn": c["issn"],
                "journal_keys": c["journal_keys"],
                "title": c["title"],
                "canonical": c["canonical"],
                "year": c["year"],
                "volume": c["volume"],
                "missing": c["official_missing"],
                "confirmed_missing": c["confirmed_missing"],
                "observed_missing": c["missing"],
                "new_missing": c["new_missing"],
                "late_issues": c["late_issues"],
                "gap_changed": c["gap_changed"],
                "confirmed": c["confirmed"],
                "covered": c["covered"],
                "suspended": c["suspended"],
                "status": "GAP" if c["official_missing"] else "COMPLETE",
                "titles": c["titles"],
                "issues": c["issues"],
                "record_ids": c["record_ids"],
                "title_conflicts": c.get("title_conflicts", []),
            }
        )

    ctx["chains"] = chains
    ctx["gaps"] = out
    ctx["title_conflicts"] = title_conflicts
    ctx["processed_years"] = sorted(restored_years, key=int)
    ctx["computed_years"] = sorted(computed_years, key=int)
    ctx["pending_years"] = sorted(pending_years, key=int)
    # 合刊裁决阶段的装订冲突保留；补上跨刊名版本同期的装订冲突。
    known = {
        (r.get("issue"), r.get("copy"), r.get("left"), r.get("right"))
        for r in ctx["binding_conflicts"]
    }
    for conflict in binding_conflicts:
        key = (conflict["issue"], conflict["copy"], conflict["left"], conflict["right"])
        if key not in known:
            ctx["binding_conflicts"].append(conflict)
            known.add(key)
    return report(
        out,
        缺期=sum(len(r["missing"]) for r in out),
        年度链=len(out),
        刊名版本=sum(len(r["titles"]) for r in out),
    )
