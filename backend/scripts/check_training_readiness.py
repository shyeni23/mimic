"""
Cheap, safe-to-run-anytime operational check: how close is the interaction
log to having enough volume for the two-tower model to actually learn
something (vs. memorizing noise)?

Run:  python scripts/check_training_readiness.py

Prints current row count, growth rate, and an ETA to the training
threshold -- no training, no model load, just a Supabase read.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db.supabase_client import get_supabase

# Why 10K: below this, a two-tower model with even a small embedding dim
# (64-128) has more trainable parameters than training examples for many
# users/items, and will overfit to noise rather than learn real
# preference structure. 10K is a conservative floor, not a guarantee of
# good results -- more is better, this is just where it stops being
# obviously premature.
MIN_INTERACTIONS_FOR_TRAINING = 10_000
# Positive signals only (click/add_to_cart/tryon) -- these are what the
# two-tower model actually trains on (see train_two_tower.py's triple
# extraction). Raw `view` events inflate the row count without adding
# training signal, so track this separately for an honest readiness read.
POSITIVE_EVENT_TYPES = ("click", "add_to_cart", "tryon")


def run():
    sb = get_supabase()
    # count="exact" queries are correct regardless of row volume -- PostgREST
    # only caps the ROWS a plain .select().execute() returns (default 1000),
    # not a count. The positive-signal number below used to come from fetching
    # ALL interaction rows into Python and filtering there, which silently
    # truncated at 1000 rows and under-reported once the table passed that
    # size (confirmed live: reported 634 positives out of 10,872 real ones).
    total = sb.table("interactions").select("id", count="exact").limit(1).execute().count
    positive_count = (
        sb.table("interactions").select("id", count="exact")
        .in_("event_type", POSITIVE_EVENT_TYPES).limit(1).execute().count
    )

    print(f"Total interaction rows:      {total}")
    print(f"Positive signal rows:        {positive_count}  (click/add_to_cart/tryon -- what training actually uses)")
    print(f"Training threshold:          {MIN_INTERACTIONS_FOR_TRAINING}")

    if not total:
        print("\nNo data yet -- nothing to estimate from.")
        return

    # Only need the min/max created_at for the collection-span estimate, not
    # every row -- two tiny ordered queries instead of paginating the whole
    # table.
    earliest = (sb.table("interactions").select("created_at")
                .order("created_at", desc=False).limit(1).execute().data)
    latest = (sb.table("interactions").select("created_at")
              .order("created_at", desc=True).limit(1).execute().data)
    span_days = 0.1
    if earliest and latest:
        start = datetime.fromisoformat(earliest[0]["created_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(latest[0]["created_at"].replace("Z", "+00:00"))
        span_days = max((end - start).total_seconds() / 86400, 0.1)
    rate_per_day = positive_count / span_days

    print(f"Collection span:             {span_days:.1f} days")
    print(f"Positive signals/day (avg):  {rate_per_day:.2f}")

    remaining = MIN_INTERACTIONS_FOR_TRAINING - positive_count
    if remaining <= 0:
        print(f"\nREADY: {positive_count} positive signals >= {MIN_INTERACTIONS_FOR_TRAINING} threshold.")
        print("Run: python scripts/train_two_tower.py")
    elif rate_per_day > 0:
        eta_days = remaining / rate_per_day
        print(f"\nNOT READY: {remaining} more positive signals needed.")
        print(f"At the current rate, that's ~{eta_days:.0f} days away "
              f"({eta_days / 30:.1f} months) -- this will accelerate once the "
              f"store has real foot traffic instead of dev testing.")
    else:
        print(f"\nNOT READY: {remaining} more positive signals needed. "
              f"No collection rate to estimate from yet.")


if __name__ == "__main__":
    run()
