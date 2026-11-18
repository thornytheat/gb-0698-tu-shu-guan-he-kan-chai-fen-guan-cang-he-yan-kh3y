"""年度馆藏链：把同一年、同一卷号下前后相继的刊名版本合并成一条链。

关键约定：
- 一条链内保留每个期次自己的原刊名（issue_title），不把旧刊名改写成新刊名；
- 只有同年度、同卷号、期次覆盖严格前后相继（互不重叠）的刊名/ISSN 才归并，
  这正是年中更换刊名的形态；覆盖相交则视为不同刊物或冲突，不合并；
- 同一 ISSN 下的不同刊名天然属于同一链；
- 已确认的年度缺口快照优先，晚到旧刊只登记不改写。
"""
import re
import unicodedata
from collections import defaultdict

# 常规期号上限；增刊不参与年度缺口。
EXPECTED_ISSUES = 12


def norm_title(text):
    """仅做兼容归一，保留可读的原刊名内容。"""
    return unicodedata.normalize("NFKC", str(text or "")).strip()


def compact_title(text):
    return re.sub(r"\s+", "", norm_title(text)).casefold()


def titles_related(left, right):
    """判断两个刊名是否可能属于同一刊物的前后版本（仅用于跨 ISSN 合并）。"""
    a, b = compact_title(left), compact_title(right)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if long.startswith(short):
        return True
    return False


def _issue_order(issue):
    try:
        return int(issue)
    except (TypeError, ValueError):
        return 10**6


def _row_issue_set(row):
    return set(map(str, row.get("issues", [])))


def _successive(left_issues, right_issues):
    """两组期次是否构成“前半年旧刊 → 后半年新刊”的相继关系。

    要求覆盖互不重叠、严格分处前后两段，且后一段不是从第 1 期重新起算。
    这样才能把年中改名的两个版本接成一条链，同时避免误并同卷号的独立刊物。
    """
    if not left_issues or not right_issues or left_issues & right_issues:
        return False
    earlier, later = (left_issues, right_issues) if min(left_issues, key=_issue_order) < min(
        right_issues, key=_issue_order
    ) else (right_issues, left_issues)
    if max(earlier, key=_issue_order) >= min(later, key=_issue_order):
        return False  # 期次交错，不是前后版本
    if "1" not in earlier or "1" in later:
        return False  # 后一段须从年中接续，而非另起一年
    return True


def _row_names(row):
    name = row.get("canonical") or row.get("issue_title") or row.get("title")
    return compact_title(name)


def _related(left_rows, right_rows):
    """跨 ISSN 合并需要刊名同族的额外证据；同 ISSN 不适用。

    同 ISSN 下刊名可以完全更换（年中改版），但 ISSN 已变时，仅凭同卷号
    与互补期次容易把同卷的独立刊物误并，故要求刊名有承接关系。
    """
    left = {_row_names(r) for r in left_rows}
    right = {_row_names(r) for r in right_rows}
    return any(titles_related(a, b) for a in left for b in right)


def _merge_base_groups(rows):
    """按 ISSN 建立基础组，再合并同年度同卷号的前后期刊名版本。"""
    bases = defaultdict(list)
    for row in rows:
        bases[(row["journal_key"], row["year"], str(row.get("volume", "")))].append(row)

    keys = list(bases)
    parent = {key: key for key in keys}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, left in enumerate(keys):
        for right in keys[i + 1:]:
            if left[0] == right[0]:
                continue  # 同 ISSN 已在同一基础组
            if left[1] != right[1] or left[2] != right[2]:
                continue
            if not _related(bases[left], bases[right]):
                continue
            left_issues = set().union(*(_row_issue_set(r) for r in bases[left]))
            right_issues = set().union(*(_row_issue_set(r) for r in bases[right]))
            if _successive(left_issues, right_issues):
                union(left, right)

    merged = defaultdict(list)
    for key, group in bases.items():
        merged[find(key)].extend(group)
    return list(merged.values())


def _issue_entries(rows):
    entries = defaultdict(list)
    for row in rows:
        for issue in row.get("issues", []):
            entries[str(issue)].append(
                {
                    "issue": str(issue),
                    "title": norm_title(row.get("issue_title") or row.get("title")),                    "canonical": row.get("canonical") or row.get("issue_title") or row.get("title"),
                    "issn": row.get("journal_key", ""),
                    "binding": row.get("binding", ""),
                    "copy": row.get("copy", ""),
                    "record_id": row.get("record_id", ""),
                    "line": row.get("line", 0),
                    "status": row.get("status", ""),
                    "note": row.get("note", ""),
                    "volume": row.get("volume", ""),
                }
            )
    return entries


def _build_versions(entries):
    """按生效期次顺序生成刊名版本，并检出同一年度内的刊名冲突。"""
    title_conflicts = []
    ordered = sorted(entries, key=_issue_order)
    versions = []
    seen_at = {}

    for issue in ordered:
        records = entries[issue]
        # 同复本同期出现两个刊名才是冲突；不同复本在过渡期可各带一个刊名。
        by_copy = defaultdict(set)
        for record in records:
            by_copy[record["copy"]].add(norm_title(record["title"]))
        conflicting = sorted(
            {name for names in by_copy.values() if len(names) > 1 for name in names}
        )
        if conflicting:
            title_conflicts.append(
                {
                    "issue": issue,
                    "reason": "TITLE_CONFLICT",
                    "titles": conflicting,
                    "records": [r["record_id"] for r in records],
                }
            )

        first = sorted(
            records, key=lambda r: (r["copy"], r["issn"], r["title"], r["record_id"])
        )[0]
        title = first["title"]
        canonical = first["canonical"]
        issn = first["issn"]
        if versions and versions[-1]["title"] == title and versions[-1]["issn"] == issn:
            versions[-1]["to_issue"] = issue
            versions[-1]["record_ids"].append(first["record_id"])
        else:
            if title in seen_at and seen_at[title] != len(versions) - 1:
                title_conflicts.append(
                    {
                        "issue": issue,
                        "reason": "TITLE_SEQUENCE",
                        "titles": [title],
                        "records": [first["record_id"]],
                    }
                )
            versions.append(
                {
                    "title": title,
                    "canonical": canonical,
                    "issn": issn,
                    "from_issue": issue,
                    "to_issue": issue,
                    "record_ids": [first["record_id"]],
                }
            )
            seen_at[title] = len(versions) - 1
    return versions, title_conflicts


def _effective_version(versions, issue):
    """某个期次生效的刊名版本；缺失期次取最近的在版版本。"""
    order = _issue_order(issue)
    for version in reversed(versions):
        if _issue_order(version["from_issue"]) <= order <= _issue_order(version["to_issue"]):
            return version
    before = [v for v in versions if _issue_order(v["to_issue"]) < order]
    if before:
        return max(before, key=lambda v: _issue_order(v["to_issue"]))
    return versions[0] if versions else None


def _title_candidates(versions, issue):
    """缺失期次没有到馆记录时，列出可能的当期刊名版本。"""
    order = _issue_order(issue)
    spanning = [
        v for v in versions
        if _issue_order(v["from_issue"]) <= order <= _issue_order(v["to_issue"])
    ]
    if spanning:
        return [spanning[0]["title"]]
    before = [v for v in versions if _issue_order(v["to_issue"]) < order]
    after = [v for v in versions if _issue_order(v["from_issue"]) > order]
    candidates = []
    if before:
        candidates.append(max(before, key=lambda v: _issue_order(v["to_issue"]))["title"])
    if after:
        candidates.append(min(after, key=lambda v: _issue_order(v["from_issue"]))["title"])
    return sorted(set(candidates))


def _chain_key(year, volume, issns, title):
    return "|".join(
        [str(year), str(volume), ",".join(sorted(set(issns))), compact_title(title)]
    )


def build_chain(rows):
    """把一组记录整理成一条年度馆藏链及其逐期凭据。"""
    entries = _issue_entries(rows)
    versions, title_conflicts = _build_versions(entries)
    latest = versions[-1] if versions else None
    year = str(rows[0].get("year", "")) if rows else ""
    volume = str(rows[0].get("volume", "")) if rows else ""
    issns = sorted({r["journal_key"] for r in rows})
    title = latest["title"] if latest else ""
    canonical = latest["canonical"] if latest else title
    issn = latest["issn"] if latest else (issns[0] if issns else "")

    issues = []
    for number in range(1, EXPECTED_ISSUES + 1):
        issue = str(number)
        records = entries.get(issue, [])
        held = [r for r in records if r["status"] == "held"]
        suspended = [r for r in records if r["status"] == "suspended"]
        status = "held" if held else "suspended" if suspended else "missing"
        version = _effective_version(versions, issue)
        title_for_issue = records[0]["title"] if records else (version["title"] if version else title)
        # 缺失期次没有到馆记录，刊名按版本区间推断，并列出可能的候选。
        candidates = _title_candidates(versions, issue) if not records else [title_for_issue]
        canonical_for_issue = (
            records[0]["canonical"] if records else (version["canonical"] if version else canonical)
        )
        issn_for_issue = records[0]["issn"] if records else (version["issn"] if version else issn)
        issues.append(
            {
                "issue": issue,
                "title": title_for_issue,
                "title_candidates": candidates,
                # record=当期刊名直接来自到馆记录；version=缺期按所在刊名版本推断。
                "title_source": "record" if records else "version",
                "titles": sorted({r["title"] for r in records}),
                "canonical": canonical_for_issue,
                "issn": issn_for_issue,
                "status": status,
                "binding": records[0]["binding"] if records else "",
                "bindings": sorted({r["binding"] for r in records if r["binding"]}),
                "copy": records[0]["copy"] if records else "",
                "record_ids": [r["record_id"] for r in records],
                "records": [
                    {
                        "record_id": r["record_id"],
                        "line": r["line"],
                        "copy": r["copy"],
                        "binding": r["binding"],
                        "status": r["status"],
                        "title": r["title"],
                        "issn": r["issn"],
                        "volume": r["volume"],
                        "issue": r["issue"],
                        "note": r["note"],
                    }
                    for r in records
                ],
            }
        )

    covered = {str(i) for i in range(1, EXPECTED_ISSUES + 1) if any(
        r["status"] == "held" for r in entries.get(str(i), [])
    )}
    suspended_set = {str(i) for i in range(1, EXPECTED_ISSUES + 1) if any(
        r["status"] == "suspended" for r in entries.get(str(i), [])
    )}
    missing_set = {str(i) for i in range(1, EXPECTED_ISSUES + 1)} - covered - suspended_set

    binding_conflicts = []
    for issue, records in entries.items():
        if len({r["issn"] for r in records}) <= 1:
            continue
        by_copy = defaultdict(list)
        for record in records:
            by_copy[record["copy"]].append(record)
        for copy, same_copy in by_copy.items():
            bindings = {r["binding"] for r in same_copy if r["binding"]}
            if len(bindings) > 1:
                binding_conflicts.append(
                    {
                        "issue": issue,
                        "copy": copy,
                        "left": sorted(r["record_id"] for r in same_copy)[0],
                        "right": sorted(r["record_id"] for r in same_copy)[-1],
                        "reason": "BINDING_CONFLICT",
                    }
                )

    return (
        {
            "chain_key": _chain_key(year, volume, issns, canonical or title),
            "issn": issn,
            "journal_keys": issns,
            "year": year,
            "volume": volume,
            "title": title,
            "canonical": canonical,
            "titles": versions,
            "issues": issues,
            "title_conflicts": title_conflicts,
            "binding_conflicts": binding_conflicts,
            "covered": sorted(covered, key=_issue_order),
            "suspended": sorted(suspended_set, key=_issue_order),
            "missing": sorted(missing_set, key=_issue_order),
            "record_ids": sorted({r["record_id"] for r in rows}),
        },
        title_conflicts,
        binding_conflicts,
    )


def build_chains(rows):
    chains, title_conflicts, binding_conflicts = [], [], []
    for group in _merge_base_groups(rows):
        chain, title_bad, binding_bad = build_chain(group)
        chains.append(chain)
        title_conflicts.extend(title_bad)
        binding_conflicts.extend(binding_bad)
    chains.sort(key=lambda c: (_issue_order(c["volume"]), c["issn"], c["chain_key"]))
    return chains, title_conflicts, binding_conflicts


def match_confirmed(chain, snapshots):
    """按年度、卷号与 ISSN 交集匹配已确认的年度缺口快照。"""
    issns = set(chain.get("journal_keys") or [chain.get("issn", "")])
    for snapshot in snapshots or []:
        if str(snapshot.get("year")) != str(chain.get("year")):
            continue
        if str(snapshot.get("volume")) != str(chain.get("volume")):
            continue
        if issns & set(snapshot.get("issns") or []):
            return snapshot
    return None


def apply_confirmed(chain, snapshot):
    """把已确认缺口叠加到本次核验结果；晚到记录只登记，不改写已确认缺口。"""
    chain["confirmed"] = bool(snapshot)
    observed = {
        entry["issue"]: entry
        for entry in chain["issues"]
        if entry["status"] in {"held", "suspended"}
    }
    if not snapshot:
        chain["confirmed_missing"] = []
        chain["official_missing"] = list(chain["missing"])
        chain["late_issues"] = []
        chain["new_missing"] = []
        chain["gap_changed"] = []
        return chain
    confirmed_missing = list(snapshot.get("missing") or [])
    # 已确认缺口里现在到馆的期次：晚到旧刊，只作凭据，不撤销缺口。
    late = sorted(
        {issue for issue in confirmed_missing if issue in observed},
        key=_issue_order,
    )
    # 确认后新出现的缺期：提示复核，不改写已确认缺口。
    new_missing = sorted(
        set(chain["missing"]) - set(confirmed_missing),
        key=_issue_order,
    )
    chain["confirmed_missing"] = confirmed_missing
    chain["official_missing"] = confirmed_missing
    chain["late_issues"] = late
    chain["late_records"] = [
        record
        for issue in late
        for record in observed[issue]["records"]
    ]
    chain["new_missing"] = new_missing
    chain["gap_changed"] = sorted(set(late) | set(new_missing), key=_issue_order)
    return chain
