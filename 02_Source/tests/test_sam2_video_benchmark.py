import numpy as np

from nova_layer.sam2_video_benchmark import intersection_over_union, make_scenario


def test_video_benchmark_scenarios_are_deterministic() -> None:
    scenario = make_scenario("occlusion_recovery")

    assert len(scenario.frames) == 7
    assert scenario.master_frame == 3
    assert scenario.master_mask.shape == (180, 320)
    assert set(scenario.ground_truth) == {0, 6}
    repeated = make_scenario("occlusion_recovery")
    assert np.array_equal(scenario.frames[0].image, repeated.frames[0].image)


def test_iou_handles_identical_and_disjoint_masks() -> None:
    truth = np.zeros((4, 4), dtype=np.uint8)
    truth[:2] = 255
    disjoint = np.zeros((4, 4), dtype=np.uint8)
    disjoint[2:] = 255

    assert intersection_over_union(truth, truth) == 1.0
    assert intersection_over_union(disjoint, truth) == 0.0


def test_frame_exit_has_empty_endpoint_truth() -> None:
    scenario = make_scenario("frame_exit")

    assert not scenario.ground_truth[0].any()
    assert not scenario.ground_truth[6].any()
    assert scenario.master_mask.any()
