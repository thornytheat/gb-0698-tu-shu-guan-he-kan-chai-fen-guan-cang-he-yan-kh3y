from app.report import report


def request_list(gaps):
    """按年度链生成补录任务；每期带当期刊名，且同一 ISSN·年度·期次只出现一次。"""
    tasks = []
    seen = set()
    for gap in gaps:
        issues = {entry["issue"]: entry for entry in gap.get("issues", [])}
        late = set(map(str, gap.get("late_issues", [])))
        # 刊名冲突未裁决前不生成补录任务，避免对身份不清的刊物下单式补录。
        if gap.get("title_conflicts"):
            continue
        for issue in gap.get("missing", []):
            entry = issues.get(str(issue), {})
            issn = entry.get("issn") or gap.get("issn", "")
            key = (issn, str(gap.get("year", "")), str(issue))
            if key in seen:
                continue
            seen.add(key)
            tasks.append(
                {
                    "issn": issn,
                    "title": entry.get("title") or gap.get("title", ""),
                    # 缺失期次的刊名若只能由版本区间推断，保留候选供人工核对。
                    "title_candidates": entry.get("title_candidates") or [],
                    "title_source": entry.get("title_source", ""),
                    "canonical": gap.get("canonical", ""),
                    "year": gap.get("year", ""),
                    "volume": gap.get("volume", ""),
                    "issue": issue,
                    "chain_key": gap.get("chain_key", ""),
                    "confirmed": bool(gap.get("confirmed")),
                    "late": str(issue) in late,
                    "status": "待补录",
                }
            )
    return tasks


def apply(ctx):
    ctx["final"] = request_list(ctx["gaps"])
    ctx["blocked"] = bool(
        ctx["binding_conflicts"] or ctx["identity_conflicts"] or ctx.get("title_conflicts")
    )
    late = sum(len(g.get("late_issues", [])) for g in ctx["gaps"])
    return report(
        ctx["final"],
        补录任务=len(ctx["final"]),
        冲突=len(ctx["binding_conflicts"]) + len(ctx["identity_conflicts"]) + len(ctx.get("title_conflicts", [])),
        晚到记录=late,
    )
