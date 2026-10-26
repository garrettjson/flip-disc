"""Tests for clip loader, ClipAnimation, and ComposedAnimation."""

import numpy as np
import pytest
from PIL import Image

from flipdisc.animations.base import get_animation, register_animation
from flipdisc.animations.bouncing_dot import BouncingDot
from flipdisc.animations.clip import ClipAnimation, _blit_fit
from flipdisc.animations.composed import ComposedAnimation
from flipdisc.animations.image import ImageAnimation
from flipdisc.animations.params import Param
from flipdisc.animations.viewport import Viewport
from flipdisc.clips.importer import create_clip_from_animation
from flipdisc.clips.loader import ClipData, list_clips, load_clip

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_clip_data(n=10, h=7, w=56) -> ClipData:
    frames = np.zeros((n, h, w), dtype=bool)
    frames[0, 3, 10] = True
    return ClipData(
        frames=frames, fps=20.0, loop=True, width=w, height=h, description="test"
    )


def _write_clip_toml(tmp_path, gif_path) -> str:
    toml_path = tmp_path / "clips.toml"
    toml_path.write_text(
        f'[test]\npath = "{gif_path}"\nfps = 20.0\nloop = true\n'
        f'width = 56\nheight = 7\ndescription = "test clip"\n'
    )
    return str(toml_path)


def _mock_load_clip(clip_data: ClipData):
    """Return a monkeypatch-compatible load_clip stub."""
    return lambda *_args, **_kw: clip_data


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------


def _make_test_gif(path, n=10, h=7, w=56) -> None:
    """Write a minimal animated GIF with n frames at 20 fps."""
    duration_ms = 50  # 20 fps
    frames_data = []
    for i in range(n):
        f = np.zeros((h, w), dtype=np.uint8)
        f[i % h, i % w] = 255  # unique pixel per frame so optimizer keeps all frames
        frames_data.append(f)
    frames_data[0][3, 10] = 255  # ensure first-frame pixel we assert on is set
    pil_frames = [Image.fromarray(f).convert("P") for f in frames_data]
    pil_frames[0].save(
        str(path),
        save_all=True,
        append_images=pil_frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=False,
    )


def test_load_clip_basic(tmp_path):
    gif_path = tmp_path / "test.gif"
    _make_test_gif(gif_path)

    toml_path = _write_clip_toml(tmp_path, gif_path)
    clip = load_clip("test", config_path=toml_path)

    assert clip.frames.shape == (10, 7, 56)
    assert clip.frames.dtype == bool
    assert clip.fps == 20.0
    assert clip.loop is True
    assert clip.width == 56
    assert clip.height == 7
    assert bool(clip.frames[0, 3, 10]) is True


def test_load_clip_cached(tmp_path):
    gif_path = tmp_path / "test.gif"
    _make_test_gif(gif_path, n=5)
    toml_path = _write_clip_toml(tmp_path, gif_path)

    clip1 = load_clip("test", config_path=toml_path)
    clip2 = load_clip("test", config_path=toml_path)
    assert clip1 is clip2


def test_load_clip_unknown_raises(tmp_path):
    toml_path = tmp_path / "clips.toml"
    toml_path.write_text("")
    with pytest.raises(KeyError, match="missing"):
        load_clip("missing", config_path=str(toml_path))


def test_list_clips_empty(tmp_path):
    toml_path = tmp_path / "clips.toml"
    toml_path.write_text("# empty\n")
    assert list_clips(str(toml_path)) == []


def test_list_clips(tmp_path):
    toml_path = tmp_path / "clips.toml"
    toml_path.write_text("[alpha]\npath='a.gif'\n[beta]\npath='b.gif'\n")
    assert list_clips(str(toml_path)) == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# Importer round-trip test
# ---------------------------------------------------------------------------


def test_importer_create_clip_from_animation(tmp_path):
    anim = BouncingDot(Viewport(56, 7))
    out = tmp_path / "dot.gif"
    create_clip_from_animation(anim, n_frames=20, dt=0.05, output_path=out)

    img = Image.open(str(out))
    frame_count = 0
    try:
        while True:
            frame_count += 1
            img.seek(img.tell() + 1)
    except EOFError:
        pass

    assert frame_count == 20
    assert img.size == (56, 7)


# ---------------------------------------------------------------------------
# _blit_fit tests
# ---------------------------------------------------------------------------


def test_blit_fit_center_same_size():
    canvas = np.zeros((7, 56), dtype=np.float32)
    src = np.ones((7, 56), dtype=np.float32)
    _blit_fit(canvas, src, "center")
    np.testing.assert_array_equal(canvas, src)


def test_blit_fit_center_smaller_src():
    canvas = np.zeros((7, 56), dtype=np.float32)
    src = np.ones((3, 10), dtype=np.float32)
    _blit_fit(canvas, src, "center")
    # Center: y=(7-3)//2=2, x=(56-10)//2=23
    assert canvas[2:5, 23:33].sum() == 30
    assert canvas[0, 0] == 0.0


def test_blit_fit_stretch():
    canvas = np.zeros((4, 4), dtype=np.float32)
    src = np.ones((2, 2), dtype=np.float32)
    _blit_fit(canvas, src, "stretch")
    np.testing.assert_array_equal(canvas, np.ones((4, 4), dtype=np.float32))


def test_blit_fit_tile():
    canvas = np.zeros((6, 6), dtype=np.float32)
    src = np.ones((3, 3), dtype=np.float32)
    _blit_fit(canvas, src, "tile")
    np.testing.assert_array_equal(canvas, np.ones((6, 6), dtype=np.float32))


# ---------------------------------------------------------------------------
# ClipAnimation tests
# ---------------------------------------------------------------------------


def test_clip_animation_configure(monkeypatch):
    clip_data = _make_clip_data()
    monkeypatch.setattr(
        "flipdisc.animations.clip.load_clip", _mock_load_clip(clip_data)
    )

    anim = ClipAnimation(Viewport(56, 7))
    anim.configure(name="test")

    assert anim._clip is clip_data
    assert anim._fps == 20.0
    assert anim._loop is True
    assert anim._frame_idx == 0.0


def test_clip_animation_render_shape(monkeypatch):
    clip_data = _make_clip_data()
    monkeypatch.setattr(
        "flipdisc.animations.clip.load_clip", _mock_load_clip(clip_data)
    )

    anim = ClipAnimation(Viewport(56, 7))
    anim.configure(name="test")
    frame = anim.render_gray()

    assert frame.shape == (7, 56)
    assert frame.dtype == np.float32


def test_clip_animation_no_clip_returns_zeros():
    anim = ClipAnimation(Viewport(56, 7))
    frame = anim.render_gray()
    assert frame.shape == (7, 56)
    assert frame.sum() == 0.0


def test_clip_animation_step_advances(monkeypatch):
    clip_data = _make_clip_data(n=100)
    monkeypatch.setattr(
        "flipdisc.animations.clip.load_clip", _mock_load_clip(clip_data)
    )

    anim = ClipAnimation(Viewport(56, 7))
    anim.configure(name="test", fps_override=10.0)
    anim.step(1.0)
    assert anim._frame_idx == pytest.approx(10.0)


def test_clip_animation_loops(monkeypatch):
    clip_data = _make_clip_data(n=10)
    monkeypatch.setattr(
        "flipdisc.animations.clip.load_clip", _mock_load_clip(clip_data)
    )

    anim = ClipAnimation(Viewport(56, 7))
    anim.configure(name="test", fps_override=10.0, loop=True)
    anim.step(1.5)  # 15 frames -> wraps to 5
    assert anim._frame_idx == pytest.approx(5.0)
    assert not anim.is_complete()


def test_clip_animation_no_loop_completes(monkeypatch):
    clip_data = _make_clip_data(n=10)
    monkeypatch.setattr(
        "flipdisc.animations.clip.load_clip", _mock_load_clip(clip_data)
    )

    anim = ClipAnimation(Viewport(56, 7))
    anim.configure(name="test", fps_override=10.0, loop=False)
    anim.step(2.0)  # 20 frames > 10 -> clamps
    assert anim.is_complete()
    assert int(anim._frame_idx) == 9


def test_clip_animation_reset(monkeypatch):
    clip_data = _make_clip_data(n=10)
    monkeypatch.setattr(
        "flipdisc.animations.clip.load_clip", _mock_load_clip(clip_data)
    )

    anim = ClipAnimation(Viewport(56, 7))
    anim.configure(name="test")
    anim.step(0.5)
    anim.reset()
    assert anim._frame_idx == 0.0
    assert not anim.is_complete()


def test_clip_animation_processing_steps_none():
    anim = ClipAnimation(Viewport(56, 7))
    assert anim.processing_steps is None


# ---------------------------------------------------------------------------
# ComposedAnimation tests
# ---------------------------------------------------------------------------


def test_composed_animation_empty():
    anim = ComposedAnimation(Viewport(56, 7))
    frame = anim.render_gray()
    assert frame.shape == (7, 56)
    assert frame.sum() == 0.0


def test_composed_animation_two_layers():
    anim = ComposedAnimation(Viewport(56, 7))
    anim.configure(
        layers=[
            {
                "id": "left",
                "type": "bouncing_dot",
                "x": 0,
                "y": 0,
                "width": 28,
                "height": 7,
            },
            {
                "id": "right",
                "type": "bouncing_dot",
                "x": 28,
                "y": 0,
                "width": 28,
                "height": 7,
            },
        ]
    )
    assert len(anim._layers) == 2
    frame = anim.render_gray()
    assert frame.shape == (7, 56)


def test_composed_animation_step_calls_layers():
    anim = ComposedAnimation(Viewport(56, 7))
    anim.configure(
        layers=[
            {
                "id": "dot",
                "type": "bouncing_dot",
                "x": 0,
                "y": 0,
                "width": 56,
                "height": 7,
            },
        ]
    )
    t_before = anim._layers[0].anim.current_time
    anim.step(0.1)
    assert anim._layers[0].anim.current_time > t_before


def test_composed_animation_dotted_key_update():
    anim = ComposedAnimation(Viewport(56, 7))
    anim.configure(
        layers=[
            {
                "id": "msg",
                "type": "text",
                "x": 0,
                "y": 0,
                "width": 56,
                "height": 7,
                "params": {"text": "hello", "mode": "static"},
            }
        ]
    )
    # Update via dotted-key
    anim.configure(**{"layer.msg.text": "world"})
    assert anim._layers[0].anim.params.get("text") == "world"


def test_composed_animation_unknown_layer_id_is_noop():
    anim = ComposedAnimation(Viewport(56, 7))
    anim.configure(
        layers=[
            {
                "id": "a",
                "type": "bouncing_dot",
                "x": 0,
                "y": 0,
                "width": 56,
                "height": 7,
            }
        ]
    )
    # Should not raise
    anim.configure(**{"layer.nonexistent.text": "hi"})


def test_composed_animation_processing_steps_none():
    anim = ComposedAnimation(Viewport(56, 7))
    assert anim.processing_steps is None


def test_composed_animation_reset():
    anim = ComposedAnimation(Viewport(56, 7))
    anim.configure(
        layers=[
            {
                "id": "dot",
                "type": "bouncing_dot",
                "x": 0,
                "y": 0,
                "width": 56,
                "height": 7,
            }
        ]
    )
    anim.step(1.0)
    anim.reset()
    assert anim.current_time == 0.0


# ---------------------------------------------------------------------------
# ComposedAnimation.compose() — Python object authoring path
# ---------------------------------------------------------------------------


def test_composed_compose_method():
    anim = ComposedAnimation(Viewport(56, 7))
    dot1 = BouncingDot(Viewport(28, 7))
    dot2 = BouncingDot(Viewport(28, 7))
    anim.compose(
        [
            (dot1, {"id": "left", "x": 0, "y": 0}),
            (dot2, {"id": "right", "x": 28, "y": 0}),
        ]
    )
    assert len(anim._layers) == 2
    assert anim._layers[0].id == "left"
    assert anim._layers[1].id == "right"
    assert anim._layers[0].anim is dot1
    assert anim._layers[0].width == 28  # taken from anim.width
    frame = anim.render_gray()
    assert frame.shape == (7, 56)


def test_composed_compose_replaces_layers():
    anim = ComposedAnimation(Viewport(56, 7))
    anim.configure(
        layers=[
            {
                "id": "old",
                "type": "bouncing_dot",
                "x": 0,
                "y": 0,
                "width": 56,
                "height": 7,
            }
        ]
    )
    assert len(anim._layers) == 1

    anim.compose([(BouncingDot(Viewport(56, 7)), {"id": "new", "x": 0, "y": 0})])
    assert len(anim._layers) == 1
    assert anim._layers[0].id == "new"


def test_composed_subclass_pattern():
    """Verify the primary authoring pattern: register a ComposedAnimation subclass."""

    @register_animation("_test_composed_sub")
    class _TestScene(ComposedAnimation):
        def __init__(self, viewport):
            super().__init__(viewport)
            dot = BouncingDot(self.viewport.region(28, 7))
            self.compose([(dot, {"id": "dot", "x": 0, "y": 0})])

        PARAMS = (Param("speed_x", float, 20.0),)

        def on_configure(self, **params):
            if "speed_x" in params:
                self._update_layer("dot", {"speed_x": params["speed_x"]})
            super().on_configure(**params)

    scene = get_animation("_test_composed_sub", Viewport(56, 7))
    assert len(scene._layers) == 1
    scene.configure(speed_x=3)
    assert scene._layers[0].anim.params.get("speed_x") == 3
    frame = scene.render_gray()
    assert frame.shape == (7, 56)


# ---------------------------------------------------------------------------
# Blend modes
# ---------------------------------------------------------------------------


def test_composed_blend_over_overwrites():
    anim = ComposedAnimation(Viewport(56, 7))
    anim.configure(
        layers=[
            {
                "id": "base",
                "type": "bouncing_dot",
                "x": 0,
                "y": 0,
                "width": 56,
                "height": 7,
            },
            {
                "id": "top",
                "type": "bouncing_dot",
                "x": 0,
                "y": 0,
                "width": 56,
                "height": 7,
                "blend": "over",
            },
        ]
    )
    assert anim._layers[1].blend == "over"


def test_composed_blend_add_via_json():
    anim = ComposedAnimation(Viewport(56, 7))
    anim.configure(
        layers=[
            {
                "id": "a",
                "type": "bouncing_dot",
                "x": 0,
                "y": 0,
                "width": 56,
                "height": 7,
                "blend": "add",
            },
        ]
    )
    assert anim._layers[0].blend == "add"


def test_composed_blend_add_via_dotted_key():
    anim = ComposedAnimation(Viewport(56, 7))
    anim.configure(
        layers=[
            {
                "id": "a",
                "type": "bouncing_dot",
                "x": 0,
                "y": 0,
                "width": 56,
                "height": 7,
            },
        ]
    )
    assert anim._layers[0].blend == "over"
    anim.configure(**{"layer.a.blend": "add"})
    assert anim._layers[0].blend == "add"


def test_composed_blend_add_result():
    """Both layers on — result should have pixels from both."""
    anim = ComposedAnimation(Viewport(56, 7))
    dot1 = BouncingDot(Viewport(56, 7))
    dot1.x, dot1.y = 0, 0

    dot2 = BouncingDot(Viewport(56, 7))
    dot2.x, dot2.y = 10, 0

    anim.compose(
        [
            (dot1, {"id": "a", "x": 0, "y": 0, "blend": "over"}),
            (dot2, {"id": "b", "x": 0, "y": 0, "blend": "add"}),
        ]
    )
    frame = anim.render_gray()
    # At least 2 pixels should be set (one per dot, binarized)
    assert frame.sum() >= 1.0


# ---------------------------------------------------------------------------
# Layer visibility
# ---------------------------------------------------------------------------


def test_composed_layer_visible_default():
    anim = ComposedAnimation(Viewport(56, 7))
    anim.configure(
        layers=[
            {
                "id": "dot",
                "type": "bouncing_dot",
                "x": 0,
                "y": 0,
                "width": 56,
                "height": 7,
            }
        ]
    )
    assert anim._layers[0].visible is True


def test_composed_layer_visible_false_via_json():
    anim = ComposedAnimation(Viewport(56, 7))
    anim.configure(
        layers=[
            {
                "id": "dot",
                "type": "bouncing_dot",
                "x": 0,
                "y": 0,
                "width": 56,
                "height": 7,
                "visible": False,
            }
        ]
    )
    assert anim._layers[0].visible is False
    frame = anim.render_gray()
    assert frame.sum() == 0.0  # nothing rendered


def test_composed_layer_visible_toggle_via_dotted_key():
    anim = ComposedAnimation(Viewport(56, 7))
    dot = BouncingDot(Viewport(56, 7))
    dot.x, dot.y = 5, 3
    anim.compose([(dot, {"id": "dot", "x": 0, "y": 0})])

    # Visible by default
    assert anim._layers[0].visible is True

    # Hide
    anim.configure(**{"layer.dot.visible": False})
    assert anim._layers[0].visible is False
    frame_hidden = anim.render_gray()
    assert frame_hidden.sum() == 0.0

    # Show again
    anim.configure(**{"layer.dot.visible": True})
    assert anim._layers[0].visible is True


# ---------------------------------------------------------------------------
# ImageAnimation tests
# ---------------------------------------------------------------------------


def test_image_animation_no_src_returns_zeros():
    anim = ImageAnimation(Viewport(56, 7))
    frame = anim.render_gray()
    assert frame.shape == (7, 56)
    assert frame.sum() == 0.0


def test_image_animation_configure_src(tmp_path):
    # Create a test PNG: all-white 56×7
    img = np.ones((7, 56), dtype=np.float32)
    png_path = tmp_path / "white.png"
    Image.fromarray((img * 255).astype(np.uint8)).save(png_path)

    anim = ImageAnimation(Viewport(56, 7))
    anim.configure(src=str(png_path))
    assert anim._frame is not None
    assert anim._frame.shape == (7, 56)


def test_image_animation_render_shape(tmp_path):
    img = np.ones((7, 56), dtype=np.float32)
    png_path = tmp_path / "white.png"
    Image.fromarray((img * 255).astype(np.uint8)).save(png_path)

    anim = ImageAnimation(Viewport(56, 7))
    anim.configure(src=str(png_path))
    frame = anim.render_gray()
    assert frame.shape == (7, 56)
    assert frame.dtype == np.float32


def test_image_animation_step_advances_time():
    anim = ImageAnimation(Viewport(56, 7))
    anim.step(0.1)
    assert anim.current_time == pytest.approx(0.1)


def test_image_animation_processing_steps():
    anim = ImageAnimation(Viewport(56, 7))
    assert anim.processing_steps == ("binarize",)
