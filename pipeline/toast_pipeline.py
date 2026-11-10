#!/usr/bin/env python3
"""Toast: Meta ads -> metrics -> alerts -> dashboard payload.

Design rule that matters: every number in the output is computed here, in code.
The LLM layer in production only *explains* these facts, it never calculates
them. That is what stops the agent inventing a ROAS.

Input : data/meta_ads_sample.csv  (Marketing API insights shape)
        data/accounts.json        (account config / targets)
Output: data/toast_metrics.json   (consumed by the dashboard)
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# --- tunable thresholds (one place, versioned) -------------------------------
CTR_FLOOR = 0.008          # 0.8%
FREQ_CEILING = 3.2
MIN_SPEND_TO_JUDGE = 500.0
CPA_INFLATION = 0.22
PACING_TOLERANCE = 0.20

# Unique-reach de-duplication is approximated from daily reach. The Marketing
# API returns window frequency directly; this keeps the sample data honest.
REACH_OVERLAP = {"7": 0.45, "14": 0.28}


def f(value: str) -> float:
    return float(value or 0)


def pct(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev is None or prev == 0:
        return None
    return (cur - prev) / prev


def money(v: float) -> str:
    return f"${v:,.0f}"


def metrics(rows: list[dict], days: int) -> dict:
    spend = sum(f(r["spend"]) for r in rows)
    impressions = sum(int(r["impressions"]) for r in rows)
    clicks = sum(int(r["clicks"]) for r in rows)
    conv = sum(int(r["conversions"]) for r in rows)
    value = sum(f(r["conversion_value"]) for r in rows)
    reach = sum(int(r["reach"]) for r in rows)

    out = {
        "spend": round(spend, 2),
        "impressions": impressions,
        "clicks": clicks,
        "conversions": conv,
        "value": round(value, 2),
        "ctr": round(clicks / impressions, 5) if impressions else 0.0,
        "cpm": round(spend / impressions * 1000, 2) if impressions else 0.0,
        "cpc": round(spend / clicks, 2) if clicks else 0.0,
        "cvr": round(conv / clicks, 4) if clicks else 0.0,
        "cpa": round(spend / conv, 2) if conv else None,
        "roas": round(value / spend, 2) if spend else None,
        "frequency": round(impressions / (reach * REACH_OVERLAP[str(days)]), 2) if reach else 0.0,
    }
    return out


def with_delta(cur: dict, prev: dict) -> dict:
    keys = ["spend", "conversions", "value", "ctr", "cpm", "cpa", "roas", "frequency", "cpc"]
    return {k: pct(cur.get(k), prev.get(k)) for k in keys}


def fmt_delta(v: float | None, unit: str = "%") -> str:
    if v is None:
        return "n/a"
    sign = "+" if v >= 0 else ""
    if unit == "%":
        return f"{sign}{v * 100:.0f}%"
    return f"{sign}{v:.2f}"


def group(rows: list[dict], key: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        out[r[key]].append(r)
    return out


def weighted_frequency(rows: list[dict], days: int) -> float:
    """Aggregate frequency is impression-weighted across ad sets.

    Summing reach across entities double-counts nothing real, so an aggregate
    frequency has to be an average of the entity-level numbers, not a ratio of
    summed reach.
    """
    num = den = 0.0
    for grp in group(rows, "adset_name").values():
        m = metrics(grp, days)
        num += m["impressions"] * m["frequency"]
        den += m["impressions"]
    return round(num / den, 2) if den else 0.0


def main() -> None:
    with (DATA / "meta_ads_sample.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    accounts_cfg = {a["id"]: a for a in json.loads((DATA / "accounts.json").read_text())}

    end = max(date.fromisoformat(r["date"]) for r in rows)
    windows = {
        "7": (end - timedelta(days=6), end),
        "14": (end - timedelta(days=13), end),
    }
    prev_windows = {d: (s - timedelta(days=int(d)), s - timedelta(days=1)) for d, (s, _) in windows.items()}

    def in_window(r: dict, span: tuple[date, date]) -> bool:
        d = date.fromisoformat(r["date"])
        return span[0] <= d <= span[1]

    payload_accounts = []
    all_alerts = []
    totals = {d: {"spend": 0.0, "value": 0.0, "conversions": 0, "clicks": 0, "impressions": 0, "freq_num": 0.0, "freq_den": 0.0} for d in windows}
    totals_prev = {d: {"spend": 0.0, "value": 0.0, "conversions": 0, "clicks": 0, "impressions": 0, "freq_num": 0.0, "freq_den": 0.0} for d in windows}

    for acc_id, cfg in accounts_cfg.items():
        acc_rows = [r for r in rows if r["account_id"] == acc_id]

        kpis_by_window = {}
        for d, span in windows.items():
            cur_rows = [r for r in acc_rows if in_window(r, span)]
            prev_rows = [r for r in acc_rows if in_window(r, prev_windows[d])]
            cur = metrics(cur_rows, int(d))
            prev = metrics(prev_rows, int(d))
            cur["frequency"] = weighted_frequency(cur_rows, int(d))
            prev["frequency"] = weighted_frequency(prev_rows, int(d))
            kpis_by_window[d] = {"cur": cur, "prev": prev, "delta": with_delta(cur, prev)}

            totals[d]["spend"] += cur["spend"]
            totals[d]["value"] += cur["value"]
            totals[d]["conversions"] += cur["conversions"]
            totals[d]["clicks"] += cur["clicks"]
            totals[d]["impressions"] += cur["impressions"]
            totals[d]["freq_num"] += cur["impressions"] * cur["frequency"]
            totals[d]["freq_den"] += cur["impressions"]

            totals_prev[d]["spend"] += prev["spend"]
            totals_prev[d]["value"] += prev["value"]
            totals_prev[d]["conversions"] += prev["conversions"]
            totals_prev[d]["clicks"] += prev["clicks"]
            totals_prev[d]["impressions"] += prev["impressions"]
            totals_prev[d]["freq_num"] += prev["impressions"] * prev["frequency"]
            totals_prev[d]["freq_den"] += prev["impressions"]

        # --- 14-day series for the chart ---
        series = []
        for i in range(14):
            day = (end - timedelta(days=13 - i)).isoformat()
            day_rows = [r for r in acc_rows if r["date"] == day]
            m = metrics(day_rows, 7)
            series.append({
                "date": day,
                "spend": m["spend"],
                "value": m["value"],
                "roas": m["roas"],
                "conversions": m["conversions"],
                "cpa": m["cpa"],
            })

        # --- pacing ---
        spent_7 = kpis_by_window["7"]["cur"]["spend"]
        pace_7 = cfg["monthly_budget"] / 30 * 7
        pacing_ratio = spent_7 / pace_7 if pace_7 else 0
        pacing = {
            "monthly_budget": cfg["monthly_budget"],
            "spent_7d": round(spent_7, 2),
            "pace_7d": round(pace_7, 2),
            "ratio": round(pacing_ratio, 3),
            "projected_month": round(spent_7 / 7 * 30, 2),
        }

        # --- per-entity facts (window 7) ---
        rows_by_window = {}
        for d, span in windows.items():
            cur_rows = [r for r in acc_rows if in_window(r, span)]
            prev_rows = [r for r in acc_rows if in_window(r, prev_windows[d])]

            entity_rows = []
            for adset_name, grp in sorted(group(cur_rows, "adset_name").items()):
                prev_grp = [r for r in prev_rows if r["adset_name"] == adset_name]
                cur_m = metrics(grp, int(d))
                prev_m = metrics(prev_grp, int(d))
                campaign = grp[0]["campaign_name"]
                flags = evaluate_adset(adset_name, cur_m, prev_m, cfg, int(d))
                entity_rows.append({
                    "campaign": campaign,
                    "adset": adset_name,
                    "kpis": cur_m,
                    "prev": prev_m,
                    "delta": with_delta(cur_m, prev_m),
                    "flags": flags,
                })
            rows_by_window[d] = entity_rows

        # --- alerts (always evaluated on the trailing 7 days) ---
        alerts = []
        cur_7 = [r for r in acc_rows if in_window(r, windows["7"])]
        prev_7 = [r for r in acc_rows if in_window(r, prev_windows["7"])]

        for adset_name, grp in sorted(group(cur_7, "adset_name").items()):
            prev_grp = [r for r in prev_7 if r["adset_name"] == adset_name]
            if not prev_grp:
                continue
            cur_m = metrics(grp, 7)
            prev_m = metrics(prev_grp, 7)
            flags = evaluate_adset(adset_name, cur_m, prev_m, cfg, 7)

            # ad-level: zero-conversion creative
            for ad_name, ad_grp in sorted(group(grp, "ad_name").items()):
                ad_prev = [r for r in prev_grp if r["ad_name"] == ad_name]
                ad_m = metrics(ad_grp, 7)
                ad_pm = metrics(ad_prev, 7)
                if (
                    ad_m["spend"] >= MIN_SPEND_TO_JUDGE
                    and ad_m["conversions"] == 0
                    and ad_pm["conversions"] > 0
                ):
                    flags.append({
                        "code": "zero_conversion_ad",
                        "severity": "high",
                        "entity_level": "ad",
                        "entity": ad_name,
                        "evidence": (
                            f"{money(ad_m['spend'])} spent in 7 days with 0 conversions "
                            f"(was {ad_pm['conversions']} conv at {money(ad_pm['spend'])})"
                        ),
                        "recommendation": "Pause the ad and check tracking + landing page before relaunching.",
                        "action": {"label": "Pause ad", "api": f"POST /{ad_name}/?status=PAUSED", "auto_eligible": False},
                        "at_stake_per_day": round(ad_m["spend"] / 7, 2),
                    })

            if flags:
                alerts.append(build_alert(cfg, adset_name, grp[0]["campaign_name"], flags, cur_m, prev_m))

        if pacing_ratio > 1 + PACING_TOLERANCE or pacing_ratio < 1 - PACING_TOLERANCE:
            over = pacing_ratio > 1
            alerts.append({
                "id": f"{acc_id}-pacing",
                "account": cfg["name"],
                "account_id": acc_id,
                "severity": "medium",
                "code": "budget_pacing",
                "title": "Pacing ahead of budget" if over else "Under-delivering budget",
                "entity": f"{cfg['name']} · account",
                "why": [
                    f"7-day spend {money(spent_7)} vs {money(pace_7)} plan "
                    f"({fmt_delta(pacing_ratio - 1)})",
                    f"Projected month {money(pacing['projected_month'])} vs "
                    f"{money(cfg['monthly_budget'])} budget",
                ],
                "recommendation": (
                    "Cap the top-spending ad set by ~15% or pull budget forward only where CPA is under target."
                    if over
                    else "Raise bids on the best-performing ad set or widen the audience."
                ),
                "action": {
                    "label": "Adjust daily budget",
                    "api": "POST /{adset_id}/?daily_budget=...",
                    "auto_eligible": False,
                },
                "at_stake_per_day": round(abs(spent_7 - pace_7) / 7, 2),
            })

        insight = build_insight(cfg, kpis_by_window["7"], alerts)
        for a in alerts:
            all_alerts.append(a)

        payload_accounts.append({
            **{k: cfg[k] for k in ("id", "name", "vertical", "currency", "target_cpa", "monthly_budget")},
            "kpis": kpis_by_window,
            "pacing": pacing,
            "series": series,
            "rows": rows_by_window,
            "alerts": alerts,
            "insight": insight,
        })

    totals_payload = {}
    for d in windows:
        t = totals[d]
        p = totals_prev[d]

        def pack(s: dict) -> dict:
            return {
                "spend": round(s["spend"], 2),
                "value": round(s["value"], 2),
                "conversions": s["conversions"],
                "clicks": s["clicks"],
                "impressions": s["impressions"],
                "roas": round(s["value"] / s["spend"], 2) if s["spend"] else None,
                "cpa": round(s["spend"] / s["conversions"], 2) if s["conversions"] else None,
                "ctr": round(s["clicks"] / s["impressions"], 5) if s["impressions"] else 0.0,
                "cpm": round(s["spend"] / s["impressions"] * 1000, 2) if s["impressions"] else 0.0,
                "cpc": round(s["spend"] / s["clicks"], 2) if s["clicks"] else 0.0,
                "frequency": round(s["freq_num"] / s["freq_den"], 2) if s["freq_den"] else 0.0,
            }

        cur_pack, prev_pack = pack(t), pack(p)
        totals_payload[d] = {**cur_pack, "delta": with_delta(cur_pack, prev_pack)}

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    all_alerts.sort(key=lambda a: severity_rank.get(a["severity"], 3))

    payload = {
        "generated_at": "",
        "data_end": end.isoformat(),
        "source_rows": len(rows),
        "window_label": "trailing 7 days vs prior 7 days",
        "totals": totals_payload,
        "accounts": payload_accounts,
        "alerts": all_alerts,
    }

    (DATA / "toast_metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"data end: {end}   accounts: {len(payload_accounts)}   alerts: {len(all_alerts)}")
    for a in all_alerts:
        print(f"  [{a['severity']:6}] {a['account']:22} {a['title']}")


def evaluate_adset(name: str, cur: dict, prev: dict, cfg: dict, days: int) -> list[dict]:
    flags = []
    delta = with_delta(cur, prev)

    if cur["frequency"] >= FREQ_CEILING and (cur["frequency"] - prev["frequency"]) >= 0.5:
        severity = "high" if cur["frequency"] >= 4.2 else "medium"
        flags.append({
            "code": "audience_fatigue",
            "severity": severity,
            "entity_level": "adset",
            "entity": name,
            "evidence": (
                f"Frequency {cur['frequency']:.2f} (+{cur['frequency'] - prev['frequency']:.2f} w/w), "
                f"CTR {cur['ctr'] * 100:.2f}% ({fmt_delta(delta['ctr'])})"
            ),
            "recommendation": "Refresh creative and widen or exclude the most saturated segment.",
            "action": {"label": "Queue 2 new creatives", "api": "internal://creative-queue", "auto_eligible": False},
            "at_stake_per_day": round(cur["spend"] / days * 0.2, 2),
        })

    if cur["conversions"] > 0 and (delta["cpa"] or 0) >= CPA_INFLATION and cur["spend"] >= MIN_SPEND_TO_JUDGE:
        flags.append({
            "code": "cpa_inflation",
            "severity": "high" if (delta["cpa"] or 0) >= 0.40 else "medium",
            "entity_level": "adset",
            "entity": name,
            "evidence": (
                f"CPA {money(cur['cpa'])} vs {money(prev['cpa'])} ({fmt_delta(delta['cpa'])}); "
                f"CPM {fmt_delta(delta['cpm'])}, CVR {cur['cvr'] * 100:.1f}% "
                f"({fmt_delta(pct(cur['cvr'], prev['cvr']))})"
            ),
            "recommendation": "Check creative and audience overlap; shift budget to the best ad set while it is investigated.",
            "action": {"label": "Reduce budget 20%", "api": "POST /{adset_id}/?daily_budget=-20%", "auto_eligible": False},
            "at_stake_per_day": round(cur["spend"] / days * 0.25, 2),
        })

    if cur["conversions"] > 0 and cur["cpa"] and cur["cpa"] > cfg["target_cpa"] * 1.25:
        flags.append({
            "code": "over_target_cpa",
            "severity": "high" if cur["cpa"] > cfg["target_cpa"] * 1.6 else "medium",
            "entity_level": "adset",
            "entity": name,
            "evidence": f"CPA {money(cur['cpa'])} vs target {money(cfg['target_cpa'])}",
            "recommendation": "Rebuild the offer or creative; do not scale until CPA lands under target.",
            "action": {"label": "Cap spend", "api": "POST /{adset_id}/?daily_budget=...", "auto_eligible": False},
            "at_stake_per_day": round(cur["spend"] / days * 0.3, 2),
        })

    if cur["roas"] is not None and cur["roas"] < 1.0 and cur["spend"] >= MIN_SPEND_TO_JUDGE:
        flags.append({
            "code": "below_breakeven",
            "severity": "high",
            "entity_level": "adset",
            "entity": name,
            "evidence": f"ROAS {cur['roas']:.2f} at {money(cur['spend'])} spend over {days} days",
            "recommendation": "Pause or restructure; this ad set is losing money at the current value per conversion.",
            "action": {"label": "Pause ad set", "api": "POST /{adset_id}/?status=PAUSED", "auto_eligible": True},
            "at_stake_per_day": round((cur["spend"] - cur["value"]) / days, 2),
        })

    if cur["impressions"] > 3000 and cur["ctr"] < CTR_FLOOR:
        flags.append({
            "code": "ctr_below_floor",
            "severity": "medium",
            "entity_level": "adset",
            "entity": name,
            "evidence": f"CTR {cur['ctr'] * 100:.2f}% below {CTR_FLOOR * 100:.1f}% floor at CPM {money(cur['cpm'])}",
            "recommendation": "Hook is not landing — test new opening frames / first line before touching budget.",
            "action": {"label": "Queue hook variants", "api": "internal://creative-queue", "auto_eligible": False},
            "at_stake_per_day": round(cur["spend"] / days * 0.1, 2),
        })

    if cur["spend"] < 1 and prev["spend"] > 200:
        flags.append({
            "code": "delivery_stalled",
            "severity": "high",
            "entity_level": "adset",
            "entity": name,
            "evidence": f"No delivery for 7 days after {money(prev['spend'])} in the prior week — status still ACTIVE",
            "recommendation": "Check payment method, ad review status and audience size before assuming it is a performance issue.",
            "action": {"label": "Inspect account", "api": "GET /{adset_id}/?fields=status,effective_status", "auto_eligible": False},
            "at_stake_per_day": round(prev["spend"] / 7, 2),
        })

    return flags


def build_alert(cfg: dict, adset: str, campaign: str, flags: list[dict], cur: dict, prev: dict) -> dict:
    rank = {"high": 0, "medium": 1, "low": 2}
    # When one entity trips several rules, lead with the sharpest diagnosis:
    # "it stopped converting" is more actionable than "CPA moved".
    diagnosis = {
        "delivery_stalled": 0,
        "zero_conversion_ad": 1,
        "below_breakeven": 2,
        "audience_fatigue": 3,
        "cpa_inflation": 4,
        "over_target_cpa": 5,
        "ctr_below_floor": 6,
    }
    primary = sorted(flags, key=lambda x: (rank[x["severity"]], diagnosis.get(x["code"], 9)))[0]
    titles = {
        "audience_fatigue": "Audience fatigue",
        "cpa_inflation": "CPA inflation week on week",
        "over_target_cpa": "CPA above target",
        "below_breakeven": "Below breakeven",
        "ctr_below_floor": "CTR below floor",
        "zero_conversion_ad": "Zero conversions",
        "delivery_stalled": "Delivery stopped",
    }
    severity = primary["severity"]
    return {
        "id": f"{cfg['id']}-{adset}".replace(" ", "-").lower(),
        "account": cfg["name"],
        "account_id": cfg["id"],
        "severity": severity,
        "code": primary["code"],
        "title": titles.get(primary["code"], primary["code"]),
        "entity": f"{campaign} / {primary['entity']}" if primary["entity_level"] == "adset" else f"{campaign} / {adset} / {primary['entity']}",
        "why": [fl["evidence"] for fl in flags],
        "recommendation": primary["recommendation"],
        "action": primary["action"],
        "at_stake_per_day": round(sum(fl["at_stake_per_day"] for fl in flags), 2),
        "secondary_flags": [fl["code"] for fl in flags[1:]],
    }


def build_insight(cfg: dict, kpi: dict, alerts: list[dict]) -> str:
    cur, delta = kpi["cur"], kpi["delta"]
    parts = []
    roas_txt = f"{cur['roas']:.2f}" if cur["roas"] is not None else "n/a"
    parts.append(
        f"{cfg['name']} spent {money(cur['spend'])} in the last 7 days at ROAS {roas_txt} "
        f"({fmt_delta(delta['roas'])} w/w) and CPA {money(cur['cpa']) if cur['cpa'] else 'n/a'} "
        f"vs a {money(cfg['target_cpa'])} target."
    )
    if alerts:
        worst = alerts[0]
        parts.append(f"{len(alerts)} item(s) need attention; the most material is “{worst['title'].lower()}” on {worst['entity'].split(' / ')[-1]}.")
    else:
        parts.append("No rule-based flags fired — the account is inside its thresholds.")
    parts.append(
        "Read together with pacing: spend is "
        f"{'ahead of' if cur['spend'] > cfg['monthly_budget'] / 30 * 7 else 'behind'} plan, "
        "so efficiency fixes should not be judged in isolation from delivery."
    )
    return " ".join(parts)


if __name__ == "__main__":
    main()
