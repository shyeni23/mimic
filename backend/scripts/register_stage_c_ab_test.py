"""
Registers and activates the "stage_c_neural_blend" A/B test -- the two-tower
checkpoint (see app/services/fashion/two_tower.py), wired into
recommend_items() but OFF for every session until this is run.

Two variants, mirroring how stage_b_weights was set up (see
HANDOFF_MODULE3.md item 3):
  v1 control:    neural blend off (today's exact rule-based behaviour)
  v2 challenger: neural blend on, weight 0.35

CONSERVATIVE SPLIT ON PURPOSE -- 80% control / 20% challenger, not the 50/50
stage_b_weights used. The two-tower checkpoint is trained on 15,625
SYNTHETIC interaction triples (scripts/generate_synthetic_interactions.py),
not real customer behaviour (see two_tower.py's module docstring and
HANDOFF_MODULE3.md open issue #5) -- it has learned to imitate the heuristic
that LABELLED its training data, which is not the same claim as "it has
learned real preference." A small, measurable slice is the honest way to
find out whether it helps, without betting most of the traffic on an
unvalidated signal.

Run:
    python scripts/register_stage_c_ab_test.py
    python scripts/report_ab_test.py --name stage_c_neural_blend   # check results later
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.fashion.model_registry import activate_config, register_config
from app.services.fashion.two_tower import is_available


def run():
    if not is_available():
        print(
            "WARNING: data/models/two_tower checkpoint not found on this machine "
            "(gitignored, like every other model weight -- run scripts/train_two_tower.py "
            "first). Registering the test anyway is harmless -- get_active_config's result "
            "will simply never be used, since recommend_items() checks is_available() before "
            "honouring it -- but there is nothing to measure until the checkpoint exists here."
        )

    v1 = register_config(
        "stage_c_neural_blend", {"enabled": False, "weight": 0.0},
        notes="Control -- today's rule-based Stage B ranking, unchanged. Registered "
              "explicitly so it can run side-by-side with the challenger rather than "
              "only existing as a hardcoded fallback.",
    )
    v2 = register_config(
        "stage_c_neural_blend", {"enabled": True, "weight": 0.35},
        notes="Challenger -- blends in the two-tower checkpoint's user-context/item-"
              "embedding similarity at weight 0.35. Trained on SYNTHETIC interactions, "
              "not real customer behaviour -- this test exists to find out whether that "
              "still produces useful ranking, not to confirm it does.",
    )
    activate_config("stage_c_neural_blend", v1["version"], traffic_pct=80)
    activate_config("stage_c_neural_blend", v2["version"], traffic_pct=20)
    print(f"\nActivated: v{v1['version']} control @ 80%, v{v2['version']} challenger @ 20%")
    print("Check it any time with: python scripts/report_ab_test.py --name stage_c_neural_blend")


if __name__ == "__main__":
    run()
