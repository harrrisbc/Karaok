import numpy as np

from engine.live import blend_guide


def test_blend_guide_zero_is_instrumental():
    inst = np.ones((4, 2), dtype=np.float32)
    voc = np.full((4, 2), 0.5, dtype=np.float32)
    out = blend_guide(inst, voc, 0.0)
    assert np.allclose(out, inst)


def test_blend_guide_adds_vocals():
    inst = np.zeros((4, 2), dtype=np.float32)
    voc = np.ones((4, 2), dtype=np.float32)
    out = blend_guide(inst, voc, 0.4)
    assert np.allclose(out, 0.4)


def test_blend_guide_clips():
    inst = np.ones((2, 2), dtype=np.float32)
    voc = np.ones((2, 2), dtype=np.float32)
    out = blend_guide(inst, voc, 1.0)
    assert np.max(out) <= 1.0
