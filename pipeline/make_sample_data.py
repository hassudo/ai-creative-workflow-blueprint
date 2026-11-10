#!/usr/bin/env python3
"""Generate a synthetic Meta Ads export.

The column shape mirrors the Marketing API `insights` endpoint / Ads Manager CSV
export, so the downstream pipeline is the same code you would point at a real
export. Deterministic (seed=42) so the dashboard is reproducible.

Deliberate anomalies are injected so the rules engine has something to find:
  * Harbour Dental  / Retargeting - 180d  -> audience fatigue (frequency climbing,
                                             CTR decaying, CPA inflating)
  * NorthPeak       / Cold - Broad        -> one ad stops converting mid-flight
  * NorthPeak       / account             -> budget pacing ahead of plan
  * Calder          / Lapsed Donors       -> CPA inflation week on week
  * Brightline      / Parents - Broad     -> CTR below floor at a high CPM
  * Brightline      / Open House          -> delivery stopped while still active
"""

from __future__ import annotations

import csv
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

DAYS = 28
END = date.today() - timedelta(days=1)
START = END - timedelta(days=DAYS - 1)

ACCOUNTS = [
    {
        "id": "act_1041",
        "name": "Harbor Dental",
        "vertical": "Local services / lead-gen",
        "currency": "USD",
        "target_cpa": 120.0,
        "monthly_budget": 30000.0,
        "campaigns": [
            {
                "name": "Implants - Search Intent",
                "objective": "OUTCOME_LEADS",
                "adsets": [
                    {
                        "name": "Implants - Broad",
                        "status": "ACTIVE",
                        "spend": 550.0, "cpm": 26.0, "ctr": 0.019, "cvr": 0.060,
                        "value_per_conv": 130.0,
                        "freq_start": 1.00, "freq_growth": 0.10,
                        "ctr_decay": 0.10, "cvr_decay": 0.05, "cpm_growth": 0.04,
                        "ads": [
                            {"name": "Static - Before/After A", "share": 0.60},
                            {"name": "Static - Offer 20% B", "share": 0.40},
                        ],
                    },
                    {
                        "name": "Retargeting - 180d",
                        "status": "ACTIVE",
                        "spend": 350.0, "cpm": 18.0, "ctr": 0.021, "cvr": 0.110,
                        "value_per_conv": 130.0,
                        "freq_start": 1.10, "freq_growth": 1.10,
                        "ctr_decay": 0.30, "cvr_decay": 0.10, "cpm_growth": 0.12,
                        "ads": [
                            {"name": "Retarget - Testimonial", "share": 0.70},
                            {"name": "Retarget - Booking CTA", "share": 0.30},
                        ],
                    },
                ],
            }
        ],
    },
    {
        "id": "act_2087",
        "name": "NorthPeak Outdoors",
        "vertical": "Ecommerce / DTC",
        "currency": "USD",
        "target_cpa": 45.0,
        "monthly_budget": 55000.0,
        "campaigns": [
            {
                "name": "Prospecting - Q4",
                "objective": "OUTCOME_SALES",
                "adsets": [
                    {
                        "name": "Cold - Broad",
                        "status": "ACTIVE",
                        "spend": 1100.0, "cpm": 14.0, "ctr": 0.014, "cvr": 0.035,
                        "value_per_conv": 95.0,
                        "freq_start": 1.02, "freq_growth": 0.08,
                        "ctr_decay": 0.08, "cvr_decay": 0.05, "cpm_growth": 0.03,
                        "ads": [
                            {"name": "Video - Trail Test A", "share": 0.55, "blackout_from": 21},
                            {"name": "Static - Lifestyle B", "share": 0.45},
                        ],
                    },
                    {
                        "name": "Interest - Hiking",
                        "status": "ACTIVE",
                        "spend": 650.0, "cpm": 17.0, "ctr": 0.012, "cvr": 0.031,
                        "value_per_conv": 92.0,
                        "freq_start": 1.00, "freq_growth": 0.06,
                        "ctr_decay": 0.06, "cvr_decay": 0.04, "cpm_growth": 0.03,
                        "ads": [{"name": "Static - Gear Grid C", "share": 1.0}],
                    },
                ],
            },
            {
                "name": "Retargeting - 14d",
                "objective": "OUTCOME_SALES",
                "adsets": [
                    {
                        "name": "Cart Abandoners",
                        "status": "ACTIVE",
                        "spend": 400.0, "cpm": 22.0, "ctr": 0.028, "cvr": 0.090,
                        "value_per_conv": 90.0,
                        "freq_start": 1.40, "freq_growth": 0.20,
                        "ctr_decay": 0.04, "cvr_decay": 0.03, "cpm_growth": 0.02,
                        "ads": [{"name": "Dynamic - Cart DPA", "share": 1.0}],
                    }
                ],
            },
        ],
    },
    {
        "id": "act_3310",
        "name": "Calder Foundation",
        "vertical": "Nonprofit / fundraising",
        "currency": "USD",
        "target_cpa": 75.0,
        "monthly_budget": 50000.0,
        "campaigns": [
            {
                "name": "Year-End Giving",
                "objective": "OUTCOME_DONATIONS",
                "adsets": [
                    {
                        "name": "Lapsed Donors 12m+",
                        "status": "ACTIVE",
                        "spend": 750.0, "cpm": 21.0, "ctr": 0.016, "cvr": 0.045,
                        "value_per_conv": 120.0,
                        "freq_start": 1.10, "freq_growth": 0.35,
                        "ctr_decay": 0.18, "cvr_decay": 0.60, "cpm_growth": 0.30,
                        "ads": [
                            {"name": "Story - Matching Gift", "share": 0.50},
                            {"name": "Static - 2x Match", "share": 0.50},
                        ],
                    },
                    {
                        "name": "Lookalike - Donors 1%",
                        "status": "ACTIVE",
                        "spend": 600.0, "cpm": 19.0, "ctr": 0.013, "cvr": 0.030,
                        "value_per_conv": 120.0,
                        "freq_start": 1.00, "freq_growth": 0.10,
                        "ctr_decay": 0.06, "cvr_decay": 0.04, "cpm_growth": 0.03,
                        "ads": [{"name": "Static - Impact Grid", "share": 1.0}],
                    },
                    {
                        "name": "Warm - Email List",
                        "status": "ACTIVE",
                        "spend": 300.0, "cpm": 16.0, "ctr": 0.030, "cvr": 0.080,
                        "value_per_conv": 120.0,
                        "freq_start": 1.05, "freq_growth": 0.12,
                        "ctr_decay": 0.05, "cvr_decay": 0.03, "cpm_growth": 0.02,
                        "ads": [{"name": "Static - Donor Letter", "share": 1.0}],
                    },
                ],
            }
        ],
    },
    {
        "id": "act_4155",
        "name": "Brightline Tutoring",
        "vertical": "Education / local lead-gen",
        "currency": "USD",
        "target_cpa": 55.0,
        "monthly_budget": 21000.0,
        "campaigns": [
            {
                "name": "Back-to-School - Parents",
                "objective": "OUTCOME_LEADS",
                "adsets": [
                    {
                        "name": "Parents - Broad",
                        "status": "ACTIVE",
                        "spend": 450.0, "cpm": 38.0, "ctr": 0.0042, "cvr": 0.050,
                        "value_per_conv": 320.0,
                        "freq_start": 1.05, "freq_growth": 0.10,
                        "ctr_decay": 0.05, "cvr_decay": 0.04, "cpm_growth": 0.04,
                        "ads": [
                            {"name": "Static - Tutor Match", "share": 0.55},
                            {"name": "Static - Grade Bump", "share": 0.45},
                        ],
                    },
                    {
                        "name": "Parents - Lookalike 2%",
                        "status": "ACTIVE",
                        "spend": 350.0, "cpm": 33.0, "ctr": 0.0060, "cvr": 0.055,
                        "value_per_conv": 320.0,
                        "freq_start": 1.00, "freq_growth": 0.08,
                        "ctr_decay": 0.05, "cvr_decay": 0.04, "cpm_growth": 0.03,
                        "ads": [{"name": "Static - Parent Quote", "share": 1.0}],
                    },
                ],
            },
            {
                "name": "Open House - Nov",
                "objective": "OUTCOME_LEADS",
                "adsets": [
                    {
                        "name": "Open House - 15km",
                        "status": "ACTIVE",
                        "stall_day": 20,
                        "spend": 225.0, "cpm": 30.0, "ctr": 0.012, "cvr": 0.040,
                        "value_per_conv": 300.0,
                        "freq_start": 1.02, "freq_growth": 0.05,
                        "ctr_decay": 0.03, "cvr_decay": 0.02, "cpm_growth": 0.02,
                        "ads": [{"name": "Event - Open House", "share": 1.0}],
                    }
                ],
            },
        ],
    },
]


def jitter(rng: random.Random, pct: float) -> float:
    return 1.0 + rng.uniform(-pct, pct)


def build_rows() -> list[dict]:
    rng = random.Random(42)
    rows: list[dict] = []

    for acc in ACCOUNTS:
        for camp in acc["campaigns"]:
            for adset in camp["adsets"]:
                for ad in adset["ads"]:
                    for i in range(DAYS):
                        day = START + timedelta(days=i)
                        p = i / (DAYS - 1)

                        stalled = adset.get("stall_day") is not None and i >= adset["stall_day"]
                        if stalled:
                            rows.append({
                                "date": day.isoformat(),
                                "account_id": acc["id"],
                                "account_name": acc["name"],
                                "campaign_name": camp["name"],
                                "adset_name": adset["name"],
                                "ad_name": ad["name"],
                                "objective": camp["objective"],
                                "spend": "0.00", "impressions": "0", "reach": "0",
                                "clicks": "0", "conversions": "0", "conversion_value": "0.00",
                            })
                            continue

                        spend = (
                            adset["spend"]
                            * ad["share"]
                            * (1 + 0.05 * math.sin(i / 3.1))
                            * jitter(rng, 0.10)
                        )
                        cpm = adset["cpm"] * (1 + adset["cpm_growth"] * p) * jitter(rng, 0.05)
                        ctr = adset["ctr"] * (1 - adset["ctr_decay"] * p) * jitter(rng, 0.07)
                        cvr = adset["cvr"] * (1 - adset["cvr_decay"] * p) * jitter(rng, 0.09)
                        freq = adset["freq_start"] + adset["freq_growth"] * (p ** 1.8)

                        impressions = spend / cpm * 1000.0
                        clicks = impressions * ctr
                        conversions = clicks * cvr
                        if ad.get("blackout_from") is not None and i >= ad["blackout_from"]:
                            conversions = 0.0

                        rows.append({
                            "date": day.isoformat(),
                            "account_id": acc["id"],
                            "account_name": acc["name"],
                            "campaign_name": camp["name"],
                            "adset_name": adset["name"],
                            "ad_name": ad["name"],
                            "objective": camp["objective"],
                            "spend": f"{spend:.2f}",
                            "impressions": str(int(round(impressions))),
                            "reach": str(int(round(impressions / freq))),
                            "clicks": str(int(round(clicks))),
                            "conversions": str(int(round(conversions))),
                            "conversion_value": f"{conversions * adset['value_per_conv']:.2f}",
                        })

    return rows


def build_account_config() -> list[dict]:
    out = []
    for acc in ACCOUNTS:
        out.append({
            "id": acc["id"],
            "name": acc["name"],
            "vertical": acc["vertical"],
            "currency": acc["currency"],
            "target_cpa": acc["target_cpa"],
            "monthly_budget": acc["monthly_budget"],
        })
    return out


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    rows = build_rows()

    csv_path = DATA / "meta_ads_sample.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    config_path = DATA / "accounts.json"
    config_path.write_text(json.dumps(build_account_config(), indent=2), encoding="utf-8")

    print(f"wrote {len(rows)} rows -> {csv_path}")
    print(f"wrote account config -> {config_path}")
    print(f"window: {START} .. {END}")


if __name__ == "__main__":
    main()
