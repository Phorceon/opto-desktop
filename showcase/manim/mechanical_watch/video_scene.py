from manim import *
import numpy as np
from opto.manim_bridge import (load_forge_model, math_tex, serif_text, fix, open_curve, BG,
    BLUE_3B1B, BLUE_DIM, TEAL_3B1B, YELLOW_3B1B, GOLD_3B1B, MAROON_3B1B, GREEN_3B1B,
    RED_3B1B, PURPLE_3B1B, WHITE_3B1B, MUTED_3B1B)


class OptoEpisode(ThreeDScene):
    def construct(self):
        title = serif_text(
            "How does a mechanical wristwatch keep time?",
            height=0.53, max_width=11.8
        ).move_to([0, 0.55, 0])
        underline = Line([-3.8, -0.05, 0], [3.8, -0.05, 0], color=BLUE_3B1B)
        hook = serif_text(
            "How can a spring release its energy in precisely equal steps?",
            color=MUTED_3B1B, height=0.28, italic=True, max_width=10.5
        ).move_to([0, -0.58, 0])
        fix(title, underline, hook)
        self.play(FadeIn(title), Create(underline), FadeIn(hook), run_time=1.8)
        self.wait(1.0)
        self.play(FadeOut(title), FadeOut(underline), FadeOut(hook), run_time=0.8)

        model = load_forge_model(self)
        model.setup_camera(ambient_rate=0.07)
        model.play_blueprint_intro()

        divider = Line([0.05, -2.75, 0], [0.05, 3.25, 0], color=BLUE_DIM,
                       stroke_width=1.4)
        fix(divider)
        narration = serif_text(
            "The case protects the mechanism; the hands merely report its count.",
            height=0.25, max_width=12.6
        ).move_to([0, -3.35, 0])
        fix(narration)
        self.play(*model.move_left_anims(), Create(divider), FadeIn(narration),
                  run_time=1.5)

        def replace_narration(text):
            nonlocal narration
            new = serif_text(text, height=0.25, max_width=12.6).move_to([0, -3.35, 0])
            fix(new)
            self.play(FadeOut(narration), FadeIn(new), run_time=0.65)
            narration = new

        # Act 1: the display is a geared readout, not the timekeeper.
        self.play(*model.focus_anims({
            "case": "#58c4dd", "dial": "#83c167",
            "hands": "#ffd166", "strap": "#58c4dd"
        }, dim_opacity=0.18), run_time=1.0)
        case_callout = model.make_callout(
            "case", "protective shell", BLUE_3B1B, pos=np.array([-4.8, 2.65, 0])
        )
        hands_callout = model.make_callout(
            "hands", "12 : 1 motion works", GOLD_3B1B, pos=np.array([-4.5, -2.05, 0])
        )
        fix(case_callout, hands_callout)
        self.play(FadeIn(case_callout), FadeIn(hands_callout), run_time=0.8)

        clock_center = np.array([3.65, 0.65, 0])
        clock = Circle(radius=1.32, color=BLUE_DIM, stroke_width=2).move_to(clock_center)
        ticks = VGroup(*[
            Line(
                clock_center + 1.15 * np.array([np.cos(a), np.sin(a), 0]),
                clock_center + 1.28 * np.array([np.cos(a), np.sin(a), 0]),
                color=MUTED_3B1B, stroke_width=2
            )
            for a in np.linspace(0, TAU, 12, endpoint=False)
        ])
        dial_phase = ValueTracker(0)

        def dial_hands():
            a = dial_phase.get_value()
            minute_end = clock_center + 1.03 * np.array(
                [np.cos(PI / 2 - a), np.sin(PI / 2 - a), 0]
            )
            hour_end = clock_center + 0.69 * np.array(
                [np.cos(PI / 2 - a / 12), np.sin(PI / 2 - a / 12), 0]
            )
            minute = Line(clock_center, minute_end, color=GOLD_3B1B, stroke_width=4)
            hour = Line(clock_center, hour_end, color=TEAL_3B1B, stroke_width=6)
            hub = Dot(clock_center, radius=0.055, color=WHITE_3B1B)
            group = VGroup(hour, minute, hub)
            fix(hour, minute, hub, group)
            return group

        moving_hands = always_redraw(dial_hands)
        ratio = math_tex(r"\theta_h=\frac{\theta_m}{12}", color=GOLD_3B1B,
                         height=0.60).move_to([3.65, -1.35, 0])
        ratio_note = serif_text(
            "Twelve minute-hand revolutions move the hour hand once.",
            color=MUTED_3B1B, height=0.23, max_width=5.7
        ).move_to([3.65, -1.92, 0])
        fix(clock, ticks, ratio, ratio_note)
        self.play(Create(clock), Create(ticks), FadeIn(moving_hands),
                  Write(ratio), FadeIn(ratio_note), run_time=1.6)
        self.play(dial_phase.animate.set_value(TAU), run_time=4.0, rate_func=linear)
        self.wait(0.5)

        # Act 2: opening the case reveals stored elastic energy and the oscillator.
        replace_narration(
            "Winding coils the mainspring: elastic energy enters, but nothing yet fixes the rate."
        )
        shell_group = Group(clock, ticks, moving_hands, ratio, ratio_note,
                            case_callout, hands_callout)
        fix(shell_group)
        self.play(FadeOut(shell_group), run_time=0.7)
        model.play_cutaway(focus={
            "case": "#58c4dd", "dial": "#83c167",
            "mainspring_barrel": "#e6b85c", "balance_wheel": "#ff9f68"
        })
        self.play(*model.focus_anims({
            "crown": "#ffd166", "winding_stem": "#ffd166",
            "ratchet_and_click": "#ffd166", "mainspring": "#e6b85c"
        }, dim_opacity=0.18), run_time=1.0)
        spring_callout = model.make_callout(
            "mainspring_barrel", "stored spring energy", GOLD_3B1B,
            pos=np.array([-4.55, 2.65, 0])
        )
        balance_callout = model.make_callout(
            "balance_wheel", "the regulator", RED_3B1B,
            pos=np.array([-4.45, -2.05, 0])
        )
        fix(spring_callout, balance_callout)
        self.play(FadeIn(spring_callout), FadeIn(balance_callout), run_time=0.7)

        energy_eq = math_tex(r"U=\frac{1}{2}\kappa\theta^2", color=GOLD_3B1B,
                             height=0.62).move_to([3.8, 2.55, 0])
        ax = Axes(
            x_range=[0, 2, 1], y_range=[0, 2, 1],
            x_length=4.25, y_length=2.75,
            axis_config={"color": BLUE_DIM, "stroke_width": 1.5},
            tips=False
        ).move_to([4.35, -0.55, 0])
        energy_curve = ax.plot(lambda x: 0.5 * x ** 2, x_range=[0, 2],
                               color=GOLD_3B1B, stroke_width=3)
        energy_area = ax.get_area(
            energy_curve, x_range=[0, 1.8], color=GOLD_3B1B, opacity=0.22
        )
        xlabel = serif_text("winding angle", color=MUTED_3B1B, height=0.20
                            ).move_to([4.45, -2.23, 0])
        ylabel = serif_text("energy", color=MUTED_3B1B, height=0.20
                            ).move_to([2.15, 0.55, 0])
        wind = ValueTracker(0)
        spiral_center = np.array([1.25, 1.35, 0])

        def winding_spiral():
            w = wind.get_value()
            u = np.linspace(0, 1, 130)
            angles = TAU * (1.3 + 2.5 * w) * u
            radii = 0.10 + 0.60 * u
            pts = spiral_center + np.column_stack([
                radii * np.cos(angles), radii * np.sin(angles), np.zeros_like(u)
            ])
            spiral = open_curve(pts, color=GOLD_3B1B, stroke_width=2.6)
            x = 1.8 * w
            dot = Dot(ax.c2p(x, 0.5 * x ** 2), radius=0.065, color=YELLOW_3B1B)
            group = VGroup(spiral, dot)
            fix(spiral, dot, group)
            return group

        spring_drawing = always_redraw(winding_spiral)
        fix(energy_eq, ax, energy_curve, energy_area, xlabel, ylabel)
        self.play(Write(energy_eq), Create(ax), Create(energy_curve),
                  FadeIn(energy_area), FadeIn(xlabel), FadeIn(ylabel),
                  FadeIn(spring_drawing), run_time=1.8)
        self.play(wind.animate.set_value(1), run_time=3.6)
        self.wait(0.4)

        # Act 3: the wheel train transmits energy and establishes display ratios.
        replace_narration(
            "The barrel drives the wheel train; the fourth wheel turns once per minute."
        )
        energy_group = Group(energy_eq, ax, energy_curve, energy_area, xlabel,
                             ylabel, spring_drawing, spring_callout, balance_callout)
        fix(energy_group)
        self.play(FadeOut(energy_group), run_time=0.7)
        self.play(*model.focus_anims({
            "mainspring_barrel": "#e6b85c", "center_wheel": "#ffd166",
            "third_wheel": "#83c167", "fourth_wheel": "#58c4dd",
            "hands": "#ffd166"
        }, dim_opacity=0.18), run_time=1.0)

        gear_centers = [
            np.array([1.75, 0.95, 0]),
            np.array([3.45, 0.95, 0]),
            np.array([5.25, 0.95, 0])
        ]
        gear_radii = [0.65, 0.48, 0.34]
        gear_colors = [GOLD_3B1B, GREEN_3B1B, BLUE_3B1B]
        gear_rings = VGroup(*[
            Circle(radius=r, color=c, stroke_width=2.2).move_to(p)
            for p, r, c in zip(gear_centers, gear_radii, gear_colors)
        ])
        gear_labels = Group(
            serif_text("center", color=GOLD_3B1B, height=0.20).move_to([1.75, 0.02, 0]),
            serif_text("third", color=GREEN_3B1B, height=0.20).move_to([3.45, 0.20, 0]),
            serif_text("fourth", color=BLUE_3B1B, height=0.20).move_to([5.25, 0.38, 0])
        )
        train_phase = ValueTracker(0)

        def rotating_train():
            pieces = []
            speed = train_phase.get_value()
            for index, (center, radius, color) in enumerate(
                zip(gear_centers, gear_radii, gear_colors)
            ):
                a = speed * [1, -1.8, 60][index]
                pts = [center]
                for spoke in [0, PI / 2, PI, 3 * PI / 2]:
                    pts.append(center + 0.78 * radius * np.array(
                        [np.cos(a + spoke), np.sin(a + spoke), 0]
                    ))
                    pts.append(center)
                piece = open_curve(pts, color=color, stroke_width=2.5, smooth=False)
                pieces.append(piece)
            group = VGroup(*pieces)
            fix(*pieces, group)
            return group

        spokes = always_redraw(rotating_train)
        train_eq = math_tex(r"\omega_4=60\,\omega_c", color=BLUE_3B1B,
                            height=0.59).move_to([3.7, 2.40, 0])
        period_eq = math_tex(r"T_c=1\,\mathrm{h},\qquad T_4=60\,\mathrm{s}",
                             color=WHITE_3B1B, height=0.48).move_to([3.7, -1.05, 0])
        power_path = open_curve([
            [1.10, -1.75, 0], [2.35, -1.52, 0], [3.65, -1.68, 0],
            [5.05, -1.48, 0], [6.15, -1.72, 0]
        ], color=GOLD_3B1B, stroke_width=2)
        packet = Dot(power_path.get_start(), radius=0.075, color=YELLOW_3B1B)
        fix(gear_rings, gear_labels, train_eq, period_eq, power_path, packet)
        self.play(Create(gear_rings), FadeIn(gear_labels), FadeIn(spokes),
                  Write(train_eq), Write(period_eq), Create(power_path), FadeIn(packet),
                  run_time=1.8)
        self.play(train_phase.animate.set_value(TAU), MoveAlongPath(packet, power_path),
                  run_time=3.3, rate_func=linear)
        model.play_flow(duration=3.0)
        model.clear_flow()
        self.wait(0.3)

        # Act 4: pallets meter one half-tooth pitch on every beat.
        replace_narration(
            "The pallet fork locks and releases the escape wheel once per half-oscillation."
        )
        train_group = Group(gear_rings, gear_labels, spokes, train_eq,
                            period_eq, power_path, packet)
        fix(train_group)
        self.play(FadeOut(train_group), run_time=0.7)
        self.play(*model.focus_anims({
            "escape_wheel": "#ff9f68", "pallet_fork": "#58c4dd",
            "jewel_bearings": "#c77dff"
        }, dim_opacity=0.18), run_time=0.9)
        escape_callout = model.make_callout(
            "escape_wheel", "one controlled step per beat", RED_3B1B,
            pos=np.array([-4.55, 2.65, 0])
        )
        fix(escape_callout)
        self.play(FadeIn(escape_callout), run_time=0.6)

        escape_center = np.array([2.85, 0.85, 0])
        fork_pivot = np.array([4.75, 0.85, 0])
        beat = ValueTracker(0)
        staff = Line(fork_pivot, fork_pivot + np.array([0.85, 0, 0]),
                     color=BLUE_3B1B, stroke_width=4)
        jewel_a = Dot([3.68, 1.45, 0], radius=0.075, color=PURPLE_3B1B)
        jewel_b = Dot([3.68, 0.25, 0], radius=0.075, color=PURPLE_3B1B)

        def escapement():
            step = beat.get_value()
            rotation = step * PI / 15
            pts = []
            for tooth in range(15):
                base = tooth * TAU / 15 + rotation
                for fraction, radius in [(0.0, 0.67), (0.18, 0.91),
                                         (0.48, 0.91), (0.66, 0.67)]:
                    a = base + fraction * TAU / 15
                    pts.append(escape_center + radius * np.array(
                        [np.cos(a), np.sin(a), 0]
                    ))
            pts.append(pts[0])
            wheel = open_curve(pts, color=RED_3B1B, stroke_width=2.8, smooth=False)
            rock = 0.20 * np.sin(PI * step)
            local = np.array([
                [-1.02, 0.55, 0], [-0.12, 0.0, 0],
                [-1.02, -0.55, 0]
            ])
            rotated = []
            for p in local:
                x, y = p[0], p[1]
                rotated.append(fork_pivot + np.array([
                    x * np.cos(rock) - y * np.sin(rock),
                    x * np.sin(rock) + y * np.cos(rock), 0
                ]))
            fork = open_curve(rotated, color=BLUE_3B1B, stroke_width=5, smooth=False)
            hub = Dot(fork_pivot, radius=0.06, color=WHITE_3B1B)
            group = VGroup(wheel, fork, hub)
            fix(wheel, fork, hub, group)
            return group

        escape_motion = always_redraw(escapement)
        step_eq = math_tex(r"\Delta\phi=\frac{\pi}{Z}=\frac{\pi}{15}=12^\circ",
                           color=RED_3B1B, height=0.58).move_to([3.85, 2.55, 0])
        beat_eq = math_tex(r"2\ \mathrm{beats\ per\ oscillation}",
                           color=WHITE_3B1B, height=0.47).move_to([3.85, -1.20, 0])
        lock_note = serif_text(
            "lock → unlock → impulse → lock", color=MUTED_3B1B,
            height=0.24, italic=True
        ).move_to([3.85, -1.85, 0])
        fix(staff, jewel_a, jewel_b, step_eq, beat_eq, lock_note)
        self.play(FadeIn(escape_motion), Create(staff), FadeIn(jewel_a),
                  FadeIn(jewel_b), Write(step_eq), Write(beat_eq),
                  FadeIn(lock_note), run_time=1.7)
        self.play(beat.animate.set_value(8), run_time=4.0, rate_func=linear)
        model.play_flow(duration=3.0)
        model.clear_flow()

        # Act 5: the balance and hairspring form the harmonic time reference.
        replace_narration(
            "The hairspring restores the balance: its oscillation period determines every beat."
        )
        escape_group = Group(escape_motion, staff, jewel_a, jewel_b,
                             step_eq, beat_eq, lock_note, escape_callout)
        fix(escape_group)
        self.play(FadeOut(escape_group), run_time=0.7)
        self.play(*model.focus_anims({
            "balance_wheel": "#ff9f68", "hairspring": "#58c4dd",
            "pallet_fork": "#58c4dd", "escape_wheel": "#ff9f68"
        }, dim_opacity=0.18), run_time=1.0)
        hair_callout = model.make_callout(
            "hairspring", "restoring torque  −κθ", BLUE_3B1B,
            pos=np.array([-4.65, 2.65, 0])
        )
        fix(hair_callout)
        self.play(FadeIn(hair_callout), run_time=0.6)

        period_formula = math_tex(
            r"T=2\pi\sqrt{\frac{I}{\kappa}}", color=BLUE_3B1B, height=0.64
        ).move_to([3.65, 2.65, 0])
        balance_center = np.array([1.75, 0.75, 0])
        balance_ring = Circle(radius=0.76, color=RED_3B1B,
                              stroke_width=3).move_to(balance_center)
        wave_ax = Axes(
            x_range=[0, 2, 1], y_range=[-1.2, 1.2, 1],
            x_length=3.45, y_length=2.65,
            axis_config={"color": BLUE_DIM, "stroke_width": 1.4}, tips=False
        ).move_to([4.75, 0.05, 0])
        wave = wave_ax.plot(lambda t: 0.85 * np.cos(TAU * t),
                            x_range=[0, 2], color=TEAL_3B1B, stroke_width=2.5)
        wave_label = serif_text("balance angle", color=MUTED_3B1B,
                                height=0.20).move_to([4.7, -1.65, 0])
        oscillator_phase = ValueTracker(0)
        stiffness = ValueTracker(1.0)

        def harmonic_balance():
            phase = oscillator_phase.get_value()
            k = stiffness.get_value()
            theta = 0.72 * np.cos(TAU * phase * np.sqrt(k))
            spoke_pts = []
            for a in [theta, theta + PI / 2, theta + PI, theta + 3 * PI / 2]:
                spoke_pts.append(balance_center)
                spoke_pts.append(balance_center + 0.73 * np.array(
                    [np.cos(a), np.sin(a), 0]
                ))
            spokes_local = open_curve(spoke_pts, color=RED_3B1B,
                                      stroke_width=3.4, smooth=False)
            u = np.linspace(0, 1, 130)
            radii = 0.10 + 0.48 * u
            angles = theta * (1 - u) + TAU * (2.8 + 0.7 * (k - 1)) * u
            spring_pts = balance_center + np.column_stack([
                radii * np.cos(angles), radii * np.sin(angles), np.zeros_like(u)
            ])
            spring = open_curve(spring_pts, color=BLUE_3B1B, stroke_width=2.1)
            t = phase % 2
            y = 0.85 * np.cos(TAU * phase * np.sqrt(k))
            wave_dot = Dot(wave_ax.c2p(t, y), radius=0.06, color=YELLOW_3B1B)
            group = VGroup(spokes_local, spring, wave_dot)
            fix(spokes_local, spring, wave_dot, group)
            return group

        oscillator = always_redraw(harmonic_balance)
        numeric = math_tex(
            r"T=0.250\,\mathrm{s},\quad f_0=4\,\mathrm{Hz},\quad 28{,}800\ \mathrm{beats/h}",
            color=WHITE_3B1B, height=0.43, max_width=5.9
        ).move_to([3.65, -2.05, 0])
        stiffness_note = serif_text(
            "larger κ  →  shorter T", color=BLUE_3B1B, height=0.22, italic=True
        ).move_to([1.75, -0.35, 0])
        fix(period_formula, balance_ring, wave_ax, wave, wave_label, numeric, stiffness_note)
        self.play(Write(period_formula), Create(balance_ring), Create(wave_ax),
                  Create(wave), FadeIn(wave_label), FadeIn(oscillator),
                  FadeIn(stiffness_note), run_time=1.7)
        self.play(oscillator_phase.animate.set_value(4),
                  stiffness.animate.set_value(1.25), run_time=5.5, rate_func=linear)
        self.play(Write(numeric), Indicate(period_formula, color=YELLOW_3B1B),
                  run_time=1.2)

        # Finale: energy source and time reference are distinct, then reunited.
        replace_narration(
            "The mainspring supplies energy; the balance decides exactly when to spend it."
        )
        board = Group(divider, period_formula, balance_ring, wave_ax, wave,
                      wave_label, oscillator, numeric, stiffness_note, hair_callout)
        fix(board)
        self.play(*model.focus_anims(None), FadeOut(board), run_time=0.9)
        self.play(*model.center_anims(), run_time=1.5)

        finale = math_tex(
            r"U_{\mathrm{spring}}\ \longrightarrow\ \mathrm{metered\ impulses}"
            r"\ \longrightarrow\ \theta_{\mathrm{hands}}",
            color=GOLD_3B1B, height=0.53, max_width=8.8
        ).move_to([0, -2.35, 0])
        resolution = serif_text(
            "A spring stores the energy. A harmonic oscillator parcels it into time.",
            color=WHITE_3B1B, height=0.28, italic=True, max_width=9.8
        ).move_to([0, 2.75, 0])
        fix(finale, resolution)
        self.play(Write(finale), FadeIn(resolution), run_time=1.5)
        self.begin_ambient_camera_rotation(rate=0.12)
        self.wait(4.0)
        self.stop_ambient_camera_rotation()
        self.wait(0.5)
