"""Tests for WeatherAnimation and WeatherIconAnimation."""

import numpy as np

from flipdisc.animations.precipitation import RainEffect, SnowEffect
from flipdisc.animations.viewport import Viewport
from flipdisc.animations.weather import WeatherAnimation
from flipdisc.animations.weather_icon import _CONDITIONS, WeatherIconAnimation

ALL_CONDITIONS = list(_CONDITIONS)


class TestWeatherIconAnimation:
    def test_all_conditions_render(self):
        for cond in ALL_CONDITIONS:
            icon = WeatherIconAnimation(Viewport(28, 28))
            icon.configure(condition=cond)
            frame = icon.render_gray()
            assert frame.shape == (28, 28)
            assert frame.dtype == np.float32

    def test_unknown_condition_falls_back(self):
        icon = WeatherIconAnimation(Viewport(28, 28))
        icon.configure(condition="hail")
        frame = icon.render_gray()
        assert frame.shape == (28, 28)
        # Should not raise and should have some lit pixels (cloudy fallback)
        assert frame.max() > 0.0

    def test_icon_is_top_right_aligned(self):
        """Icon should be placed top-right, so bottom-left should be mostly dark."""
        icon = WeatherIconAnimation(Viewport(28, 28))
        icon.configure(condition="sunny")
        frame = icon.render_gray()
        # Bottom-left 20x8 region should be dark (few or no lit pixels)
        bottom_left = frame[20:28, 0:8]
        assert bottom_left.sum() < 5, "Bottom-left region has too many lit pixels"


class TestWeatherAnimation:
    def test_all_conditions_render_without_exception(self):
        for cond in ALL_CONDITIONS:
            anim = WeatherAnimation(Viewport(28, 28))
            anim.configure(temp=72, condition=cond, unit="F")
            frame = anim.render_gray()
            assert frame.shape == (28, 28)
            assert frame.max() >= 0.0

    def test_default_renders(self):
        anim = WeatherAnimation(Viewport(28, 28))
        frame = anim.render_gray()
        assert frame.shape == (28, 28)

    def test_temp_text_updates(self):
        anim = WeatherAnimation(Viewport(28, 28))
        anim.configure(temp=72, condition="sunny", unit="F")
        frame1 = anim.render_gray()
        anim.configure(temp=55)
        frame2 = anim.render_gray()
        # Frames should differ because temperature changed
        assert not np.array_equal(frame1, frame2)

    def test_unit_change_rerenders(self):
        anim = WeatherAnimation(Viewport(28, 28))
        anim.configure(temp=22, condition="cloudy", unit="C")
        frame_c = anim.render_gray()
        anim.configure(unit="F")
        frame_f = anim.render_gray()
        # Unit is not displayed (only number + degree symbol) — frames are identical
        assert np.array_equal(frame_c, frame_f)

    def test_condition_update_does_not_raise(self):
        anim = WeatherAnimation(Viewport(28, 28))
        anim.configure(temp=68, condition="sunny")
        anim.configure(condition="rain")  # should not raise
        frame = anim.render_gray()
        assert frame.shape == (28, 28)

    def test_step_does_not_raise(self):
        anim = WeatherAnimation(Viewport(28, 28))
        anim.configure(temp=72, condition="sunny")
        for _ in range(10):
            anim.step(1 / 60)
        anim.render_gray()

    def test_params_stored(self):
        anim = WeatherAnimation(Viewport(28, 28))
        anim.configure(temp=72, condition="sunny", unit="F")
        assert anim.params.get("temp") == 72
        assert anim.params.get("condition") == "sunny"
        assert anim.params.get("unit") == "F"


class TestMoonPhaseIcon:
    def test_full_moon_has_many_pixels(self):
        icon = WeatherIconAnimation(Viewport(28, 28))
        icon.configure(condition="moon", moon_phase=0.5)
        frame = icon.render_gray()
        lit = (frame > 0.5).sum()
        assert lit > 100, f"Full moon should have many lit pixels, got {lit}"

    def test_new_moon_shows_thin_crescent(self):
        icon = WeatherIconAnimation(Viewport(28, 28))
        icon.configure(condition="moon", moon_phase=0.0)
        frame = icon.render_gray()
        lit = (frame > 0.5).sum()
        # Clamped to minimum crescent — visible but thin
        assert 5 < lit < 30, f"New moon should show thin crescent, got {lit}"

    def test_full_more_than_quarter(self):
        icon = WeatherIconAnimation(Viewport(28, 28))
        icon.configure(condition="moon", moon_phase=0.5)
        full_lit = (icon.render_gray() > 0.5).sum()

        icon.configure(condition="moon", moon_phase=0.25)
        quarter_lit = (icon.render_gray() > 0.5).sum()

        assert full_lit > quarter_lit, (
            f"Full ({full_lit}) should have more lit pixels than quarter ({quarter_lit})"
        )

    def test_first_quarter_right_side_lit(self):
        """First quarter (0.25): right side should be lit, left dark."""
        icon = WeatherIconAnimation(Viewport(28, 28))
        icon.configure(condition="moon", moon_phase=0.25)
        frame = icon.render_gray()
        # Split around moon center column (21)
        left = (frame[:, :21] > 0.5).sum()
        right = (frame[:, 21:] > 0.5).sum()
        assert right > left, f"Right ({right}) should exceed left ({left})"

    def test_moon_phase_forwarded_from_weather(self):
        anim = WeatherAnimation(Viewport(28, 28))
        anim.configure(temp=55, condition="moon", moon_phase=0.25)
        icon_layer = None
        for layer in anim._layers:
            if layer.id == "icon":
                icon_layer = layer
                break
        assert icon_layer is not None
        assert icon_layer.anim._moon_phase == 0.25

    def test_default_phase_is_full(self):
        icon = WeatherIconAnimation(Viewport(28, 28))
        icon.configure(condition="moon")
        assert icon._moon_phase == 0.5


class TestSnowEffect:
    def test_particles_spawn_and_fall(self):
        effect = SnowEffect(
            cloud_cols_range=(13, 22),
            spawn_y=10,
            max_y=27,
            spawn_rate=10.0,
            fall_speed=6.0,
        )
        # Step enough to spawn particles
        for _ in range(30):
            effect.step(1 / 60)
        assert len(effect._particles) > 0
        # Particles should have moved below spawn_y
        assert any(p.y > 10 for p in effect._particles)

    def test_particles_culled_offscreen(self):
        effect = SnowEffect(
            cloud_cols_range=(13, 22),
            spawn_y=10,
            max_y=27,
            spawn_rate=5.0,
            fall_speed=100.0,
        )
        for _ in range(60):
            effect.step(1 / 60)
        # With very fast fall speed, particles should be culled
        # Remaining particles should be near max_y or recently spawned
        for p in effect._particles:
            assert p.y <= 30  # max_y + 2 tolerance

    def test_render_blits_pixels(self):
        effect = SnowEffect(
            cloud_cols_range=(13, 22), spawn_y=10, max_y=27, spawn_rate=20.0
        )
        for _ in range(30):
            effect.step(1 / 60)
        canvas = np.zeros((28, 28), dtype=np.float32)
        effect.render(canvas)
        assert canvas.sum() > 0, "Snow particles should blit onto canvas"

    def test_reset_clears_particles(self):
        effect = SnowEffect(
            cloud_cols_range=(13, 22), spawn_y=10, max_y=27, spawn_rate=10.0
        )
        for _ in range(30):
            effect.step(1 / 60)
        assert len(effect._particles) > 0
        effect.reset()
        assert len(effect._particles) == 0

    def test_configure_updates_params(self):
        effect = SnowEffect(
            cloud_cols_range=(13, 22), spawn_y=10, max_y=27, spawn_rate=2.0
        )
        effect.configure(spawn_rate=5.0, fall_speed=10.0)
        assert effect._spawn_rate == 5.0
        assert effect._fall_speed == 10.0

    def test_non_overlapping_spawn_x(self):
        effect = SnowEffect(
            cloud_cols_range=(13, 22), spawn_y=10, max_y=27, spawn_rate=100.0
        )
        # Spawn many particles rapidly
        for _ in range(60):
            effect.step(1 / 60)
        xs = [p.x for p in effect._particles]
        # Verify particles spawn at varied x positions
        assert len(set(xs)) > 1, "Particles should spawn at varied x"

    def test_all_particles_fall_in_lockstep(self):
        effect = SnowEffect(
            cloud_cols_range=(13, 22),
            spawn_y=10,
            max_y=27,
            spawn_rate=5.0,
            fall_speed=6.0,
        )
        # Spawn a few particles
        for _ in range(60):
            effect.step(1 / 60)
        # Record each particle's offset from spawn_y
        offsets = [p.y - 10 for p in effect._particles]
        # All offsets should be non-negative integers (moved in whole-pixel steps)
        for off in offsets:
            assert off >= 0
            assert off == int(off), "Particles should be at integer positions"


class TestSnowWeatherIcon:
    def test_snow_condition_creates_precip(self):
        icon = WeatherIconAnimation(Viewport(28, 28))
        icon.configure(condition="snow")
        assert icon._precip is not None

    def test_non_snow_condition_no_precip(self):
        icon = WeatherIconAnimation(Viewport(28, 28))
        icon.configure(condition="sunny")
        assert icon._precip is None

    def test_snow_renders_with_particles(self):
        icon = WeatherIconAnimation(Viewport(28, 28))
        icon.configure(condition="snow", spawn_rate=20.0)
        for _ in range(30):
            icon.step(1 / 60)
        frame = icon.render_gray()
        assert frame.shape == (28, 28)
        # Should have pixels from both cloud and snow particles
        assert frame.sum() > 0

    def test_switching_condition_clears_precip(self):
        icon = WeatherIconAnimation(Viewport(28, 28))
        icon.configure(condition="snow")
        assert icon._precip is not None
        icon.configure(condition="sunny")
        assert icon._precip is None

    def test_snow_params_forwarded_from_weather(self):
        anim = WeatherAnimation(Viewport(28, 28))
        anim.configure(temp=28, condition="snow", spawn_rate=5.0, fall_speed=10.0)
        # Find the icon layer
        icon_layer = None
        for layer in anim._layers:
            if layer.id == "icon":
                icon_layer = layer
                break
        assert icon_layer is not None
        precip = icon_layer.anim._precip
        assert precip is not None
        assert precip._spawn_rate == 5.0
        assert precip._fall_speed == 10.0


class TestRainEffect:
    def test_particles_spawn_and_fall(self):
        effect = RainEffect(
            cloud_cols_range=(13, 22), spawn_y=10, max_y=27, spawn_rate=10.0
        )
        for _ in range(30):
            effect.step(1 / 60)
        assert len(effect._particles) > 0
        assert any(p.y > 10 for p in effect._particles)

    def test_particles_culled_offscreen(self):
        effect = RainEffect(
            cloud_cols_range=(13, 22),
            spawn_y=10,
            max_y=27,
            spawn_rate=5.0,
            fall_speed=100.0,
        )
        for _ in range(60):
            effect.step(1 / 60)
        for p in effect._particles:
            assert p.y <= 30  # max_y + 2 tolerance

    def test_render_blits_pixels(self):
        effect = RainEffect(
            cloud_cols_range=(13, 22), spawn_y=10, max_y=27, spawn_rate=20.0
        )
        for _ in range(30):
            effect.step(1 / 60)
        canvas = np.zeros((28, 28), dtype=np.float32)
        effect.render(canvas)
        assert canvas.sum() > 0, "Rain particles should blit onto canvas"

    def test_reset_clears_particles(self):
        effect = RainEffect(
            cloud_cols_range=(13, 22), spawn_y=10, max_y=27, spawn_rate=10.0
        )
        for _ in range(30):
            effect.step(1 / 60)
        assert len(effect._particles) > 0
        effect.reset()
        assert len(effect._particles) == 0

    def test_configure_updates_params(self):
        effect = RainEffect(
            cloud_cols_range=(13, 22), spawn_y=10, max_y=27, spawn_rate=2.0
        )
        effect.configure(spawn_rate=5.0, fall_speed=10.0, droplet_size=3)
        assert effect._spawn_rate == 5.0
        assert effect._fall_speed == 10.0
        assert effect._droplet_size == 3

    def test_all_particles_fall_in_lockstep(self):
        effect = RainEffect(
            cloud_cols_range=(13, 22),
            spawn_y=10,
            max_y=27,
            spawn_rate=5.0,
            fall_speed=14.0,
        )
        for _ in range(60):
            effect.step(1 / 60)
        offsets = [p.y - 10 for p in effect._particles]
        for off in offsets:
            assert off >= 0
            assert off == int(off), "Particles should be at integer positions"

    def test_droplet_size_respected(self):
        effect = RainEffect(
            cloud_cols_range=(5, 25),
            spawn_y=5,
            max_y=27,
            spawn_rate=50.0,
            droplet_size=1,
        )
        for _ in range(60):
            effect.step(1 / 60)
        for p in effect._particles:
            assert len(p.shape) == 1, "With droplet_size=1, all shapes should be 1px"

    def test_vertical_shapes(self):
        effect = RainEffect(
            cloud_cols_range=(5, 25),
            spawn_y=5,
            max_y=27,
            spawn_rate=50.0,
            droplet_size=3,
        )
        for _ in range(120):
            effect.step(1 / 60)
        for p in effect._particles:
            for _dr, dc in p.shape:
                assert dc == 0, "Rain shapes must be vertical (col offset always 0)"


class TestRainWeatherIcon:
    def test_rain_condition_creates_rain_effect(self):
        icon = WeatherIconAnimation(Viewport(28, 28))
        icon.configure(condition="rain")
        assert isinstance(icon._precip, RainEffect)

    def test_wmo_code_applies_preset(self):
        icon = WeatherIconAnimation(Viewport(28, 28))
        icon.configure(condition="rain", wmo_code=65)
        precip = icon._precip
        assert isinstance(precip, RainEffect)
        assert precip._spawn_rate == 1.67
        assert precip._fall_speed == 6.0
        assert precip._droplet_size == 3

    def test_explicit_params_override_preset(self):
        icon = WeatherIconAnimation(Viewport(28, 28))
        icon.configure(condition="rain", wmo_code=65, spawn_rate=1.0, droplet_size=1)
        precip = icon._precip
        assert isinstance(precip, RainEffect)
        assert precip._spawn_rate == 1.0
        assert precip._droplet_size == 1
        # fall_speed should come from preset since not overridden
        assert precip._fall_speed == 6.0

    def test_switching_condition_clears_precip(self):
        icon = WeatherIconAnimation(Viewport(28, 28))
        icon.configure(condition="rain")
        assert icon._precip is not None
        icon.configure(condition="sunny")
        assert icon._precip is None

    def test_rain_renders_with_particles(self):
        icon = WeatherIconAnimation(Viewport(28, 28))
        icon.configure(condition="rain", spawn_rate=20.0)
        for _ in range(30):
            icon.step(1 / 60)
        frame = icon.render_gray()
        assert frame.shape == (28, 28)
        assert frame.sum() > 0

    def test_default_rain_no_wmo(self):
        icon = WeatherIconAnimation(Viewport(28, 28))
        icon.configure(condition="rain")
        precip = icon._precip
        assert isinstance(precip, RainEffect)
        assert precip._spawn_rate == 1.0
        assert precip._fall_speed == 4.67
        assert precip._droplet_size == 2


class TestRainWeatherAnimation:
    def test_rain_params_forwarded(self):
        anim = WeatherAnimation(Viewport(28, 28))
        anim.configure(
            temp=55, condition="rain", spawn_rate=5.0, fall_speed=18.0, droplet_size=3
        )
        icon_layer = None
        for layer in anim._layers:
            if layer.id == "icon":
                icon_layer = layer
                break
        assert icon_layer is not None
        precip = icon_layer.anim._precip
        assert isinstance(precip, RainEffect)
        assert precip._spawn_rate == 5.0
        assert precip._fall_speed == 18.0
        assert precip._droplet_size == 3

    def test_wmo_code_forwarded(self):
        anim = WeatherAnimation(Viewport(28, 28))
        anim.configure(temp=55, condition="rain", wmo_code=82)
        icon_layer = None
        for layer in anim._layers:
            if layer.id == "icon":
                icon_layer = layer
                break
        assert icon_layer is not None
        precip = icon_layer.anim._precip
        assert isinstance(precip, RainEffect)
        assert precip._spawn_rate == 2.0
        assert precip._fall_speed == 6.67
        assert precip._droplet_size == 3
