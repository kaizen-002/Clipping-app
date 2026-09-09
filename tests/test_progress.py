"""Progress tracking.

The rule these tests defend: a bar that moves on a clock rather than on work is
worse than no bar, because it teaches the user to distrust it.
"""

from __future__ import annotations

import pytest

from clipping.core.progress import STAGE_WEIGHTS, ProgressEvent, ProgressTracker


def collect() -> tuple[ProgressTracker, list[ProgressEvent]]:
    events: list[ProgressEvent] = []
    return ProgressTracker(events.append), events


def test_overall_never_goes_backwards_across_stages() -> None:
    tracker, events = collect()
    for stage in ("audio-fetch", "survey", "hook", "precise"):
        tracker.begin(stage)
        for percent in (0.0, 40.0, 90.0):
            tracker.update(percent)
        tracker.finish(stage)

    overalls = [event.overall_percent for event in events]
    assert overalls == sorted(overalls), f"progress went backwards: {overalls}"


def test_stage_percent_is_clamped() -> None:
    tracker, events = collect()
    tracker.begin("survey")
    tracker.update(-20.0)
    tracker.update(180.0)
    assert events[-2].stage_percent == 0.0
    assert events[-1].stage_percent == 100.0


def test_overall_reflects_the_stage_weight_not_the_stage_percent() -> None:
    """Survey at 100% is not the run at 100%: it is 45% of it."""
    tracker, events = collect()
    tracker.begin("survey")
    tracker.update(100.0)
    assert events[-1].overall_percent == pytest.approx(
        STAGE_WEIGHTS["survey"] * 100, abs=0.1
    )


def test_finished_stages_are_banked() -> None:
    tracker, events = collect()
    tracker.begin("audio-fetch")
    tracker.finish("audio-fetch")
    tracker.begin("survey")
    tracker.update(0.0)
    expected = STAGE_WEIGHTS["audio-fetch"] * 100
    assert events[-1].overall_percent == pytest.approx(expected, abs=0.1)


def test_overall_never_exceeds_one_hundred() -> None:
    tracker, events = collect()
    for stage in STAGE_WEIGHTS:
        tracker.begin(stage)
        tracker.finish(stage)
    assert max(event.overall_percent for event in events) <= 100.0


def test_updates_before_any_stage_begins_are_ignored() -> None:
    """Nothing has started, so there is nothing honest to report."""
    tracker, events = collect()
    tracker.update(50.0)
    assert events == []


def test_a_label_accompanies_every_event() -> None:
    """The bar always says which phase it is in, never just a number."""
    tracker, events = collect()
    tracker.begin("survey")
    assert events[-1].label == "Transcribing"


def test_a_sliced_stage_never_runs_backwards_between_items() -> None:
    """Per-clip stages report 0-100% each; the slice keeps them ordered.

    Regression: the adapter reported 100% for clip 1's own window, then the
    loop reset the stage to 33%, and the bar visibly ran backwards.
    """
    tracker, events = collect()
    tracker.begin("precise")
    for index in range(3):
        with tracker.slice(index, 3):
            for percent in (0.0, 50.0, 100.0):
                tracker.update(percent)

    overalls = [event.overall_percent for event in events]
    assert overalls == sorted(overalls), f"progress went backwards: {overalls}"


def test_slice_restores_the_previous_span() -> None:
    tracker, events = collect()
    tracker.begin("precise")
    with tracker.slice(0, 4):
        tracker.update(100.0)
    inside = events[-1].overall_percent
    tracker.update(100.0)
    assert events[-1].overall_percent > inside
