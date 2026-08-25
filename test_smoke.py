"""Smoke test — loads the bundled sample and verifies the core pipeline.
Run:  python tests/test_smoke.py   (or pytest tests/)"""
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from etl import load_journey_csv, journey_wide          # noqa: E402
import metrics as M                                     # noqa: E402

SAMPLE = REPO / "data" / "sample_journeys.csv"


def test_pipeline():
    long = load_journey_csv(SAMPLE)
    assert long["customer"].nunique() == 655, "expected 655 sample customers"
    orders = long.drop_duplicates(["customer", "order_seq"]).shape[0]
    assert orders == 835, "expected 835 orders in sample"

    d, cohort = M.filter_cohort(long, category="Face Malai")
    assert cohort, "Face Malai cohort should not be empty"
    loy = M.loyalty_metrics(d)
    assert 0 <= loy["V2V Loyalty %"] <= 100

    cons = M.conclusions(long)
    assert len(cons) >= 6 and all(c["a"] for c in cons)

    wide = journey_wide(long)
    assert len(wide) == 655
    print("smoke test OK — pipeline healthy")


if __name__ == "__main__":
    test_pipeline()
