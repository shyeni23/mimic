"""
Reports engagement by variant for a live recommender_configs A/B test (see
app/services/fashion/model_registry.py's report_variant_performance --
read that function's docstring for how sessions get bucketed; only
recommend_clothes- and complete_outfit-sourced interactions are counted,
since those are the callers that thread session_id into
rerank_by_compatibility).

Run:
    python scripts/report_ab_test.py                      # stage_b_weights, last 30 days
    python scripts/report_ab_test.py --name stage_b_weights --days 7
"""
import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.fashion.model_registry import list_config_history, report_variant_performance


def run(name: str, days: int):
    history = [row for row in list_config_history(name) if row["is_active"]]
    if not history:
        print(f"No active config for name={name!r} -- nothing running.")
        return

    print(f"Active variants for {name!r}:")
    for row in sorted(history, key=lambda r: r["version"]):
        print(f"  v{row['version']}  {row['traffic_pct']}% traffic  {row['config']}")
        if row.get("notes"):
            print(f"      {row['notes']}")
    print()

    report = report_variant_performance(name, days_back=days)
    if "error" in report:
        print(report["error"])
        return

    print(f"Engagement over the last {days} day(s) (recommend_clothes + complete_outfit):")
    for variant, stats in sorted(report.items()):
        rate = f"{stats['engagement_rate']:.1%}" if stats["engagement_rate"] is not None else "n/a (no impressions yet)"
        print(f"  {variant}: {stats['sessions']} sessions, {stats['shown']} shown, "
              f"{stats['engaged']} engaged -> {rate}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="stage_b_weights")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    run(args.name, args.days)
