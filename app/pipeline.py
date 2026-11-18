from pathlib import Path
from app.report import plain, reason_counts
from app.modules.m1_receive.rules import apply as stage1
from app.modules.m2_titles.rules import apply as stage2
from app.modules.m3_issues.rules import apply as stage3
from app.modules.m4_combined.rules import apply as stage4
from app.modules.m5_gaps.rules import apply as stage5
from app.modules.m6_binding.rules import apply as stage6
from app.modules.m7_supplement.rules import apply as stage7


def sample_text():
    return (Path(__file__).parent.parent / "sample_data" / "instrument.csv").read_text(
        encoding="utf-8-sig"
    )


def run(text, resume=None, confirmed=None):
    """核验；resume 提供已完成年度的检查点，confirmed 提供已归档的年度缺口快照。"""
    opts = resume or {}
    ctx = {"text": text, "quarantine": [], "reports": []}
    ctx["read_year"] = opts.get("read_year")
    ctx["write_year"] = opts.get("write_year")
    ctx["confirmed"] = confirmed
    ctx["reports"].append(stage1(ctx))
    ctx["reports"].append(stage2(ctx))
    ctx["reports"].append(stage3(ctx))
    ctx["reports"].append(stage4(ctx))
    ctx["reports"].append(stage5(ctx))
    ctx["reports"].append(stage6(ctx))
    ctx["reports"].append(stage7(ctx))
    ctx.pop("read_year", None)
    ctx.pop("write_year", None)
    ctx.pop("confirmed", None)
    ctx.pop("text", None)

    # 晚到旧刊记录：作为独立凭据登记，不计入输入隔离，也不改写已确认缺口。
    late = []
    for chain in ctx.get("chains", []):
        for record in chain.get("late_records", []):
            late.append(
                {
                    "chain_key": chain["chain_key"],
                    "year": chain["year"],
                    "volume": chain["volume"],
                    "issue": record.get("issue", ""),
                    "record_id": record.get("record_id", ""),
                    "line": record.get("line", 0),
                    "title": record.get("title", ""),
                    "binding": record.get("binding", ""),
                    "status": "晚到待复核",
                }
            )
    ctx["late"] = late

    ctx["blocked"] = bool(
        ctx.get("binding_conflicts")
        or ctx.get("identity_conflicts")
        or ctx.get("title_conflicts")
        or ctx.get("year_errors")
    )
    ctx["reasons"] = reason_counts(ctx)
    result = plain(ctx)
    result["title_versions"] = sum(len(c.get("titles", [])) for c in ctx.get("chains", []))
    result["late_records"] = len(ctx.get("late", []))
    years = sorted({str(c["year"]) for c in ctx.get("chains", [])}, key=int)
    processed = sorted(
        set(ctx.get("processed_years", [])) | set(ctx.get("computed_years", [])), key=int
    )
    result["regions"] = [
        {
            "year": year,
            "status": "restored" if year in ctx.get("processed_years", []) else "computed",
            "chains": [c["chain_key"] for c in ctx.get("chains", []) if str(c["year"]) == year],
        }
        for year in years
    ]
    result["resume"] = {
        "processed_years": processed,
        "restored_years": ctx.get("processed_years", []),
        "computed_years": ctx.get("computed_years", []),
        "pending_years": ctx.get("pending_years", []),
        # 续算起点由最后一个已恢复的年度决定；其后年度本次重新计算。
        "last_completed_year": (ctx.get("processed_years") or [None])[-1],
        "next_year": (ctx.get("computed_years") or ctx.get("pending_years") or [None])[0],
    }
    return result
