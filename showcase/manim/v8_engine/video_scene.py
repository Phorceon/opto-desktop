import numpy as np
from manim import *
from opto.manim_bridge import (
    load_forge_model, math_tex, serif_text, fix, open_curve, BG,
    BLUE_3B1B, BLUE_DIM, TEAL_3B1B, YELLOW_3B1B, GOLD_3B1B,
    MAROON_3B1B, GREEN_3B1B, RED_3B1B, PURPLE_3B1B,
    WHITE_3B1B, MUTED_3B1B,
)


class OptoEpisode(ThreeDScene):
    def construct(self):
        title = serif_text(
            "How does a V8 engine work inside?",
            height=0.66, max_width=11.8,
        ).move_to([0, 0.55, 0])
        underline = Line(
            [-2.5, -0.05, 0], [2.5, -0.05, 0],
            color=BLUE_3B1B, stroke_width=2.5,
        )
        hook = serif_text(
            "Eight pistons turn combustion into rotary power through a shared crankshaft.",
            color=MUTED_3B1B, height=0.30, italic=True, max_width=11.2,
        ).move_to([0, -0.62, 0])
        fix(title, underline, hook)
        self.play(FadeIn(title), run_time=1.0)
        self.play(Create(underline), FadeIn(hook, shift=UP * 0.15), run_time=1.0)
        self.wait(0.5)
        self.play(FadeOut(title), FadeOut(underline), FadeOut(hook), run_time=0.7)

        try:
            model = load_forge_model(self)
        except (ValueError, OSError):
            model = None

        def model_anims(method_name, *args, **kwargs):
            if model is None:
                return []
            result = getattr(model, method_name)(*args, **kwargs)
            return [] if result is None else list(result)

        if model is not None:
            model.setup_camera(ambient_rate=0.07)
            model.play_blueprint_intro()

        divider = Line(
            [0.05, -3.0, 0], [0.05, 3.25, 0],
            color=BLUE_DIM, stroke_width=1.2,
        )
        fix(divider)
        self.play(
            *model_anims("move_left_anims"),
            *model_anims("focus_anims", {
                "block": "#7f8c99",
                "cylinder_heads": "#7f8c99",
                "pistons": "#e5c07b",
                "crankshaft": "#58c4dd",
            }),
            Create(divider),
            run_time=1.4,
        )

        narration = serif_text(
            "Two banks meet at ninety degrees; every piston drives the same crankshaft.",
            height=0.28, max_width=12.6,
        ).move_to([0, -3.35, 0])
        fix(narration)
        self.play(FadeIn(narration), run_time=0.6)

        theta = ValueTracker(0.0)
        crank_center = np.array([3.55, -0.95, 0.0])
        crank_radius = 0.64
        rod_length = 1.86
        bank_angle = PI / 4
        bank_units = [
            np.array([-np.sin(bank_angle), np.cos(bank_angle), 0.0]),
            np.array([np.sin(bank_angle), np.cos(bank_angle), 0.0]),
        ]

        crank_circle = Circle(
            radius=crank_radius, color=BLUE_3B1B, stroke_width=2.0,
        ).move_to(crank_center)
        crank_hub = Dot(crank_center, radius=0.055, color=BLUE_3B1B)
        v_label = math_tex(
            r"90^\circ\ \mathrm{V\ bank}", color=MUTED_3B1B, height=0.34,
        ).move_to([3.55, 2.18, 0])
        slider_equation = math_tex(
            r"x(\theta)=r\cos\theta+\sqrt{L^2-r^2\sin^2\theta}",
            height=0.52, max_width=5.8,
        ).move_to([3.55, 2.78, 0])

        cylinders = []
        for u in bank_units:
            normal = np.array([-u[1], u[0], 0.0])
            start = crank_center + u * 0.85
            end = crank_center + u * 3.05
            for sign in (-1, 1):
                cylinders.append(open_curve(
                    [start + sign * normal * 0.34, end + sign * normal * 0.34],
                    color=MUTED_3B1B, stroke_width=1.8, smooth=False,
                ))
            cylinders.append(open_curve(
                [end - normal * 0.34, end + normal * 0.34],
                color=MUTED_3B1B, stroke_width=1.8, smooth=False,
            ))

        def slider_geometry():
            t = theta.get_value()
            pin = crank_center + crank_radius * np.array(
                [np.cos(t), np.sin(t), 0.0]
            )
            pieces = [
                open_curve(
                    [crank_center, pin], color=BLUE_3B1B,
                    stroke_width=5.0, smooth=False,
                ),
                Dot(pin, radius=0.075, color=BLUE_3B1B),
            ]
            for u, color in zip(bank_units, [GOLD_3B1B, TEAL_3B1B]):
                rel = pin - crank_center
                along = float(np.dot(rel, u))
                perpendicular_sq = float(np.dot(rel, rel) - along * along)
                reach = along + np.sqrt(max(rod_length ** 2 - perpendicular_sq, 0.01))
                wrist = crank_center + reach * u
                normal = np.array([-u[1], u[0], 0.0])
                piston = Polygon(
                    wrist - 0.20 * u - 0.29 * normal,
                    wrist - 0.20 * u + 0.29 * normal,
                    wrist + 0.20 * u + 0.29 * normal,
                    wrist + 0.20 * u - 0.29 * normal,
                    color=color, stroke_width=2.2,
                    fill_color=color, fill_opacity=0.24,
                )
                ring = open_curve(
                    [wrist + 0.10 * u - 0.28 * normal,
                     wrist + 0.10 * u + 0.28 * normal],
                    color=WHITE_3B1B, stroke_width=2.0, smooth=False,
                )
                rod = open_curve(
                    [pin, wrist], color=color, stroke_width=4.0, smooth=False,
                )
                wrist_dot = Dot(wrist, radius=0.055, color=color)
                pieces.extend([rod, piston, ring, wrist_dot])
            group = VGroup(*pieces)
            fix(*pieces, group)
            return group

        slider = always_redraw(slider_geometry)
        cylinder_group = VGroup(*cylinders)
        mechanism_lines = VGroup(crank_circle, crank_hub, cylinder_group)
        mechanism_labels = Group(v_label, slider_equation)
        fix(
            *cylinders, cylinder_group, crank_circle, crank_hub,
            mechanism_lines, v_label, slider_equation, mechanism_labels, slider,
        )
        self.play(
            Create(mechanism_lines), FadeIn(slider), FadeIn(mechanism_labels),
            run_time=1.5,
        )

        crank_callout = None
        if model is not None:
            crank_callout = model.make_callout(
                "crankshaft", "Shared crankshaft", "#58c4dd", pos=[-3.3, -2.05, 0]
            )
            fix(crank_callout)
            self.play(FadeIn(crank_callout), run_time=0.4)
            model.play_cutaway(focus={
                "block": "#596773",
                "cylinder_liners": "#7f8c99",
                "pistons": "#e5c07b",
                "connecting_rods": "#4fc3f7",
                "crankshaft": "#58c4dd",
            })
        self.play(
            theta.animate.set_value(8 * PI), rate_func=linear, run_time=6.0,
        )
        if crank_callout is not None:
            self.play(FadeOut(crank_callout), run_time=0.3)

        next_narration = serif_text(
            "Rod length fixes the stroke; combustion pressure supplies the work.",
            height=0.28, max_width=12.6,
        ).move_to([0, -3.35, 0])
        fix(next_narration)
        self.play(ReplacementTransform(narration, next_narration), run_time=0.6)
        narration = next_narration
        self.play(
            FadeOut(slider), FadeOut(mechanism_lines), FadeOut(mechanism_labels),
            *model_anims("focus_anims", {
                "pistons": "#e5c07b",
                "piston_rings": "#f5f5f5",
                "connecting_rods": "#4fc3f7",
                "crankshaft": "#58c4dd",
            }),
            run_time=0.8,
        )

        pv_axes = Axes(
            x_range=[0.7, 10.7, 1], y_range=[0, 55, 10],
            x_length=5.15, y_length=3.75,
            axis_config={"color": MUTED_3B1B, "stroke_width": 1.4},
            tips=False,
        ).move_to([3.55, 0.05, 0])
        pv_x = math_tex(r"V", color=MUTED_3B1B, height=0.35)
        pv_x.next_to(pv_axes.x_axis, DOWN, buff=0.18)
        pv_y = math_tex(r"P", color=MUTED_3B1B, height=0.35)
        pv_y.next_to(pv_axes.y_axis, LEFT, buff=0.16)
        gamma = 1.4
        compression_v = np.linspace(10.0, 1.0, 90)
        compression_p = (10.0 / compression_v) ** gamma
        expansion_v = np.linspace(1.0, 10.0, 90)
        expansion_p = 50.0 * (1.0 / expansion_v) ** gamma
        cycle_2d = np.vstack([
            np.column_stack([compression_v, compression_p]),
            np.array([[1.0, 50.0]]),
            np.column_stack([expansion_v, expansion_p]),
            np.array([[10.0, 1.0]]),
        ])
        cycle_points = np.array([pv_axes.c2p(v, p) for v, p in cycle_2d])
        cycle_fill = Polygon(
            *cycle_points, stroke_width=0,
            fill_color=GOLD_3B1B, fill_opacity=0.17,
        )
        cycle_path = open_curve(
            cycle_points, color=GOLD_3B1B, stroke_width=2.6, smooth=False,
        )
        work_formula = math_tex(
            r"W_{\mathrm{cycle}}=\oint P\,dV", color=GOLD_3B1B, height=0.52,
        ).move_to([3.55, 2.72, 0])
        efficiency_formula = math_tex(
            r"\eta_{\mathrm{Otto}}=1-r_c^{1-\gamma}=1-10^{-0.4}\approx60.2\%",
            height=0.42, max_width=5.9,
        ).move_to([3.55, -2.20, 0])
        pv_dot = Dot(pv_axes.c2p(10.0, 1.0), radius=0.065, color=YELLOW_3B1B)
        pv_labels = Group(pv_x, pv_y, work_formula)
        fix(
            pv_axes, pv_x, pv_y, pv_labels, cycle_fill, cycle_path,
            work_formula, efficiency_formula, pv_dot,
        )
        self.play(Create(pv_axes), FadeIn(pv_labels), run_time=1.0)
        self.play(FadeIn(cycle_fill), Create(cycle_path), FadeIn(pv_dot), run_time=1.0)

        ring_callout = None
        if model is not None:
            ring_callout = model.make_callout(
                "piston_rings", "Rings seal the pressure", "#f5f5f5",
                pos=[-3.25, 2.65, 0],
            )
            fix(ring_callout)
        ring_animation = FadeIn(ring_callout) if ring_callout is not None else Wait(0.4)
        self.play(
            ring_animation, MoveAlongPath(pv_dot, cycle_path),
            rate_func=linear, run_time=4.0,
        )
        self.play(FadeIn(efficiency_formula), Indicate(cycle_fill), run_time=1.0)
        if ring_callout is not None:
            self.play(FadeOut(ring_callout), run_time=0.3)

        flow_narration = serif_text(
            "Over two crank turns, one cylinder breathes in, compresses, fires, and exhales.",
            height=0.28, max_width=12.6,
        ).move_to([0, -3.35, 0])
        fix(flow_narration)
        self.play(ReplacementTransform(narration, flow_narration), run_time=0.6)
        narration = flow_narration
        self.play(
            FadeOut(pv_axes), FadeOut(pv_labels), FadeOut(cycle_fill),
            FadeOut(cycle_path), FadeOut(efficiency_formula), FadeOut(pv_dot),
            *model_anims("focus_anims", {
                "throttle_body": "#4fc3f7",
                "intake_manifold": "#4fc3f7",
                "fuel_injectors": "#e5c07b",
                "valves": "#83c167",
                "exhaust_manifolds": "#e56b50",
            }),
            run_time=0.8,
        )

        cylinder_left = open_curve(
            [[1.05, 1.75, 0], [1.05, -1.15, 0]],
            color=MUTED_3B1B, stroke_width=2.0, smooth=False,
        )
        cylinder_right = open_curve(
            [[6.05, 1.75, 0], [6.05, -1.15, 0]],
            color=MUTED_3B1B, stroke_width=2.0, smooth=False,
        )
        chamber_roof = open_curve(
            [[1.05, 1.75, 0], [1.65, 1.95, 0], [5.45, 1.95, 0], [6.05, 1.75, 0]],
            color=MUTED_3B1B, stroke_width=2.0, smooth=False,
        )
        intake_label = serif_text(
            "air + fuel", color="#4fc3f7", height=0.25,
        ).move_to([1.9, 2.42, 0])
        spark_label = serif_text(
            "spark", color=YELLOW_3B1B, height=0.25,
        ).move_to([3.55, 2.42, 0])
        exhaust_label = serif_text(
            "exhaust", color="#e56b50", height=0.25,
        ).move_to([5.2, 2.42, 0])
        phase_names = ["Intake", "Compression", "Power", "Exhaust"]
        phase_colors = ["#4fc3f7", GOLD_3B1B, YELLOW_3B1B, "#e56b50"]
        phase_labels = []
        for i, (name, color) in enumerate(zip(phase_names, phase_colors)):
            label = serif_text(name, color=color, height=0.25).move_to(
                [1.35 + i * 1.47, -2.12, 0]
            )
            phase_labels.append(label)
        valve_formula = math_tex(
            r"720^\circ=4\ \mathrm{strokes}", height=0.42,
        ).move_to([3.55, 2.91, 0])
        chamber_geometry = VGroup(cylinder_left, cylinder_right, chamber_roof)
        chamber_labels = Group(
            intake_label, spark_label, exhaust_label, *phase_labels, valve_formula,
        )
        fix(
            cylinder_left, cylinder_right, chamber_roof,
            intake_label, spark_label, exhaust_label,
            *phase_labels, valve_formula, chamber_geometry, chamber_labels,
        )

        def combustion_geometry():
            t = theta.get_value() % (4 * PI)
            piston_y = -0.43 + 0.61 * np.cos(t)
            piston = Polygon(
                [1.16, piston_y - 0.18, 0], [5.94, piston_y - 0.18, 0],
                [5.94, piston_y + 0.18, 0], [1.16, piston_y + 0.18, 0],
                color=GOLD_3B1B, stroke_width=2.0,
                fill_color=GOLD_3B1B, fill_opacity=0.23,
            )
            ring = open_curve(
                [[1.18, piston_y + 0.11, 0], [5.92, piston_y + 0.11, 0]],
                color=WHITE_3B1B, stroke_width=2.0, smooth=False,
            )
            intake_amount = 0.27 * max(np.sin(t), 0.0) if t < PI else 0.0
            exhaust_amount = (
                0.27 * max(np.sin(t - 3 * PI), 0.0)
                if 3 * PI < t < 4 * PI else 0.0
            )
            intake_valve = open_curve(
                [[1.95, 2.0, 0], [1.95, 1.42 - intake_amount, 0],
                 [2.24, 1.42 - intake_amount, 0], [1.66, 1.42 - intake_amount, 0]],
                color="#4fc3f7", stroke_width=3.0, smooth=False,
            )
            exhaust_valve = open_curve(
                [[5.15, 2.0, 0], [5.15, 1.42 - exhaust_amount, 0],
                 [5.44, 1.42 - exhaust_amount, 0], [4.86, 1.42 - exhaust_amount, 0]],
                color="#e56b50", stroke_width=3.0, smooth=False,
            )
            spark_gap = abs(t - 2 * PI)
            spark_radius = 0.07 + 0.20 * np.exp(-(spark_gap / 0.16) ** 2)
            spark = Dot([3.55, 1.48, 0], radius=spark_radius, color=YELLOW_3B1B)
            pieces = [piston, ring, intake_valve, exhaust_valve, spark]
            if t < PI:
                pieces.append(Arrow(
                    [1.85, 2.20, 0], [1.85, piston_y + 0.35, 0],
                    buff=0, color="#4fc3f7", stroke_width=2.4,
                    max_tip_length_to_length_ratio=0.16,
                ))
            elif t < 2 * PI:
                pieces.append(Arrow(
                    [3.55, piston_y + 0.35, 0], [3.55, 1.05, 0],
                    buff=0, color=GOLD_3B1B, stroke_width=2.4,
                ))
            elif t < 3 * PI:
                pieces.append(Arrow(
                    [3.55, 1.18, 0], [3.55, piston_y + 0.32, 0],
                    buff=0, color=YELLOW_3B1B, stroke_width=3.0,
                ))
            else:
                pieces.append(Arrow(
                    [5.2, piston_y + 0.35, 0], [5.2, 2.18, 0],
                    buff=0, color="#e56b50", stroke_width=2.4,
                    max_tip_length_to_length_ratio=0.16,
                ))
            stage = min(int(t / PI), 3)
            indicator = Line(
                [0.88 + stage * 1.47, -1.76, 0],
                [1.82 + stage * 1.47, -1.76, 0],
                color=phase_colors[stage], stroke_width=3.0,
            )
            pieces.append(indicator)
            group = VGroup(*pieces)
            fix(*pieces, group)
            return group

        self.play(Create(chamber_geometry), FadeIn(chamber_labels), run_time=1.0)
        combustion = always_redraw(combustion_geometry)
        fix(combustion)
        self.play(FadeIn(combustion), run_time=0.4)
        if model is not None:
            model.play_flow(duration=3.0)
        self.play(
            theta.animate.set_value(12 * PI), rate_func=linear, run_time=6.0,
        )
        if model is not None:
            model.clear_flow()
        self.play(
            FadeOut(combustion), FadeOut(chamber_geometry), FadeOut(chamber_labels),
            run_time=0.7,
        )

        timing_narration = serif_text(
            "The timing drive turns the cam at half crank speed, sequencing every valve event.",
            height=0.28, max_width=12.6,
        ).move_to([0, -3.35, 0])
        fix(timing_narration)
        self.play(
            ReplacementTransform(narration, timing_narration),
            *model_anims("focus_anims", {
                "timing_drive": "#e5c07b",
                "camshaft": "#58c4dd",
                "lifters": "#83c167",
                "pushrods": "#83c167",
                "rocker_arms": "#9a6fd0",
                "valves": "#83c167",
            }),
            run_time=0.8,
        )
        narration = timing_narration

        cam_center = np.array([1.85, 0.25, 0.0])
        cam_base = Circle(
            radius=0.45, color=BLUE_DIM, stroke_width=1.2,
        ).move_to(cam_center)
        cam_axis = Dot(cam_center, radius=0.05, color=BLUE_3B1B)
        cam_equation = math_tex(
            r"n_{\mathrm{cam}}=\frac{1}{2}n_{\mathrm{crank}}",
            color=BLUE_3B1B, height=0.49,
        ).move_to([3.65, 2.77, 0])
        lift_axes = Axes(
            x_range=[0, 720, 180], y_range=[0, 1.05, 0.5],
            x_length=3.65, y_length=2.4,
            axis_config={"color": MUTED_3B1B, "stroke_width": 1.2},
            tips=False,
        ).move_to([4.72, -0.12, 0])

        def intake_lift(angle):
            a = np.asarray(angle)
            return np.where(
                a <= 180, 0.88 * np.sin(PI * a / 180.0) ** 2, 0.0,
            )

        intake_curve = lift_axes.plot(
            intake_lift, x_range=[0, 180], color="#4fc3f7", stroke_width=2.4,
        )
        exhaust_curve = lift_axes.plot(
            lambda a: 0.88 * np.sin(PI * (a - 540.0) / 180.0) ** 2,
            x_range=[540, 720], color="#e56b50", stroke_width=2.4,
        )
        lift_word = serif_text(
            "valve lift", color=MUTED_3B1B, height=0.23,
        ).move_to([5.04, 1.35, 0])
        degrees_word = math_tex(
            r"\theta_{\mathrm{crank}}", color=MUTED_3B1B, height=0.30,
        ).next_to(lift_axes.x_axis, DOWN, buff=0.16)
        cam_static_geometry = VGroup(
            cam_base, cam_axis, lift_axes, intake_curve, exhaust_curve,
        )
        cam_labels = Group(cam_equation, lift_word, degrees_word)
        fix(
            cam_base, cam_axis, cam_equation, lift_axes,
            intake_curve, exhaust_curve, lift_word, degrees_word,
            cam_static_geometry, cam_labels,
        )

        def cam_geometry():
            t = theta.get_value()
            cam_angle = t / 2.0
            phi = np.linspace(0, TAU, 100)
            radius = 0.48 + 0.36 * np.maximum(np.cos(phi), 0.0) ** 4
            local = np.column_stack([radius * np.cos(phi), radius * np.sin(phi)])
            rotation = np.array([
                [np.cos(cam_angle), -np.sin(cam_angle)],
                [np.sin(cam_angle), np.cos(cam_angle)],
            ])
            rotated = local @ rotation.T
            points = [cam_center + np.array([p[0], p[1], 0.0]) for p in rotated]
            cam = open_curve(
                points + [points[0]], color=BLUE_3B1B,
                stroke_width=3.0, smooth=False,
            )
            lift = 0.30 * max(np.sin(t / 2.0), 0.0) ** 2
            follower = open_curve(
                [[1.85, 1.13 + lift, 0], [1.85, 1.63 + lift, 0]],
                color=GREEN_3B1B, stroke_width=3.0, smooth=False,
            )
            rocker = open_curve(
                [[1.43, 1.63 + lift, 0], [2.45, 1.48 - lift * 0.35, 0]],
                color=PURPLE_3B1B, stroke_width=3.0, smooth=False,
            )
            crank_degrees = (t % (4 * PI)) * 180.0 / PI
            lift_value = float(intake_lift(crank_degrees))
            trace = Dot(
                lift_axes.c2p(crank_degrees, lift_value),
                radius=0.06, color="#4fc3f7",
            )
            group = VGroup(cam, follower, rocker, trace)
            fix(cam, follower, rocker, trace, group)
            return group

        cam_motion = always_redraw(cam_geometry)
        fix(cam_motion)
        self.play(
            Create(cam_static_geometry), FadeIn(cam_labels), FadeIn(cam_motion),
            run_time=1.2,
        )
        self.play(
            theta.animate.set_value(16 * PI), rate_func=linear, run_time=5.0,
        )
        self.play(
            FadeOut(cam_motion), FadeOut(cam_static_geometry), FadeOut(cam_labels),
            run_time=0.6,
        )

        support_narration = serif_text(
            "Spark starts combustion; coolant removes heat while oil protects the spinning bearings.",
            height=0.28, max_width=12.6,
        ).move_to([0, -3.35, 0])
        fix(support_narration)
        self.play(
            ReplacementTransform(narration, support_narration),
            *model_anims("focus_anims", {
                "spark_plugs": "#e5c07b",
                "coolant_jackets": "#4fc3f7",
                "water_pump": "#4fc3f7",
                "oil_pump": "#e5a447",
                "main_bearings": "#e5a447",
            }),
            run_time=0.8,
        )
        narration = support_narration

        coolant_points = np.array([
            [0.9, 1.0, 0], [1.0, 1.55, 0], [2.55, 1.55, 0],
            [2.75, 0.55, 0], [2.55, -0.3, 0], [1.0, -0.3, 0],
            [0.8, 0.45, 0], [0.9, 1.0, 0],
        ])
        coolant_loop = open_curve(
            coolant_points, color="#4fc3f7", stroke_width=2.4, smooth=True,
        )
        pump = Circle(radius=0.24, color=BLUE_3B1B, stroke_width=2.5).move_to(
            [0.93, 0.61, 0]
        )
        coolant_dot = Dot(coolant_points[0], radius=0.065, color=TEAL_3B1B)
        coolant_equation = math_tex(
            r"\dot Q=\dot m\,c_p\,\Delta T", color="#4fc3f7", height=0.40,
        ).move_to([1.8, 2.08, 0])
        bearing_center = np.array([4.65, 0.48, 0.0])
        bearing_outer = Circle(
            radius=0.91, color=MUTED_3B1B, stroke_width=2.0,
        ).move_to(bearing_center)
        journal = Circle(
            radius=0.49, color=GOLD_3B1B, stroke_width=3.0,
            fill_color=GOLD_3B1B, fill_opacity=0.13,
        ).move_to(bearing_center + [0.0, -0.08, 0.0])
        oil_film = Arc(
            radius=0.68, start_angle=PI, angle=PI,
            color=GOLD_3B1B, stroke_width=6.0,
        ).move_to(bearing_center)
        oil_arrow = CurvedArrow(
            bearing_center + [0.68, 0.0, 0.0],
            bearing_center + [0.0, 0.68, 0.0],
            angle=-PI / 2, color=GOLD_3B1B, stroke_width=2.0,
        )
        bearing_equation = math_tex(
            r"\mathrm{oil\ film:}\quad \tau=\mu\,\frac{u}{h}",
            color=GOLD_3B1B, height=0.40,
        ).move_to([4.65, 2.08, 0])
        coolant_word = serif_text(
            "coolant circuit", color=MUTED_3B1B, height=0.23,
        ).move_to([1.8, -0.72, 0])
        bearing_word = serif_text(
            "pressurized main bearing", color=MUTED_3B1B, height=0.23,
        ).move_to([4.65, -0.72, 0])
        support_geometry = VGroup(
            coolant_loop, pump, bearing_outer, journal, oil_film, oil_arrow,
        )
        support_labels = Group(
            coolant_equation, bearing_equation, coolant_word, bearing_word,
        )
        fix(
            coolant_loop, pump, coolant_dot, coolant_equation,
            bearing_outer, journal, oil_film, oil_arrow, bearing_equation,
            coolant_word, bearing_word, support_geometry, support_labels,
        )
        self.play(
            Create(support_geometry), FadeIn(support_labels), FadeIn(coolant_dot),
            run_time=1.0,
        )
        self.play(
            MoveAlongPath(coolant_dot, coolant_loop),
            Rotate(journal, angle=4 * PI, about_point=bearing_center),
            rate_func=linear, run_time=3.2,
        )
        self.play(
            FadeOut(support_geometry), FadeOut(support_labels), FadeOut(coolant_dot),
            *model_anims("focus_anims", None), run_time=0.7,
        )

        torque_narration = serif_text(
            "Eight cylinders fire every ninety crank degrees, smoothing pulses into continuous torque.",
            height=0.28, max_width=12.6,
        ).move_to([0, -3.35, 0])
        fix(torque_narration)
        self.play(
            ReplacementTransform(narration, torque_narration),
            *model_anims("focus_anims", {
                "crankshaft": "#58c4dd",
                "flywheel": "#e5a447",
                "bellhousing": "#7f8c99",
                "block": "#596773",
            }),
            run_time=0.8,
        )
        narration = torque_narration

        torque_axes = Axes(
            x_range=[0, 720, 90], y_range=[0, 1.55, 0.5],
            x_length=5.55, y_length=3.25,
            axis_config={"color": MUTED_3B1B, "stroke_width": 1.3},
            tips=False,
        ).move_to([3.58, -0.02, 0])
        pulse_centers = 45.0 + 90.0 * np.arange(8)
        pulse_curves = []
        for center in pulse_centers:
            pulse = torque_axes.plot(
                lambda a, c=center: np.exp(-0.5 * ((a - c) / 20.0) ** 2),
                x_range=[max(0.0, center - 60.0), min(720.0, center + 60.0)],
                color=BLUE_DIM, stroke_width=1.0,
            )
            pulse.set_opacity(0.52)
            pulse_curves.append(pulse)

        def total_torque(a):
            a = np.asarray(a)
            return sum(
                np.exp(-0.5 * ((a - center) / 20.0) ** 2)
                for center in pulse_centers
            )

        total_curve = torque_axes.plot(
            total_torque, x_range=[0, 720],
            color=GOLD_3B1B, stroke_width=3.0,
        )
        firing_formula = math_tex(
            r"\Delta\theta_{\mathrm{fire}}=\frac{720^\circ}{8}=90^\circ",
            color=GOLD_3B1B, height=0.48,
        ).move_to([3.58, 2.65, 0])
        mean_formula = math_tex(
            r"T_{\mathrm{avg}}=\frac{8W_{\mathrm{ind}}}{4\pi}",
            height=0.40,
        ).move_to([3.58, -2.13, 0])
        torque_word = serif_text(
            "summed crank torque", color=MUTED_3B1B, height=0.23,
        ).move_to([4.75, 1.77, 0])
        torque_dot = Dot(
            torque_axes.c2p(0, float(total_torque(0))),
            radius=0.06, color=YELLOW_3B1B,
        )
        pulse_group = VGroup(*pulse_curves)
        fix(
            torque_axes, *pulse_curves, pulse_group, total_curve,
            firing_formula, mean_formula, torque_word, torque_dot,
        )

        flywheel_callout = None
        if model is not None:
            flywheel_callout = model.make_callout(
                "flywheel", "Flywheel stores rotational energy", "#e5a447",
                pos=[-3.35, -2.05, 0],
            )
            fix(flywheel_callout)
        flywheel_animation = (
            FadeIn(flywheel_callout) if flywheel_callout is not None else Wait(0.4)
        )
        self.play(
            Create(torque_axes), FadeIn(pulse_group),
            FadeIn(firing_formula), flywheel_animation,
            run_time=1.1,
        )
        self.play(Create(total_curve), FadeIn(torque_word), run_time=1.0)
        self.play(
            MoveAlongPath(torque_dot, total_curve), rate_func=linear, run_time=4.0,
        )
        self.play(FadeIn(mean_formula), Indicate(total_curve), run_time=1.0)
        if flywheel_callout is not None:
            self.play(FadeOut(flywheel_callout), run_time=0.3)

        self.play(
            FadeOut(torque_axes), FadeOut(pulse_group), FadeOut(total_curve),
            FadeOut(firing_formula), FadeOut(mean_formula), FadeOut(torque_word),
            FadeOut(torque_dot), FadeOut(divider), FadeOut(narration),
            *model_anims("center_anims"),
            *model_anims("focus_anims", None),
            run_time=1.4,
        )

        finale = math_tex(
            r"W_{\mathrm{cycle}}=\sum_{k=1}^{8}\oint P_k\,dV_k,\qquad "
            r"P_{\mathrm{out}}=T_{\mathrm{avg}}\,\omega",
            color=GOLD_3B1B, height=0.58, max_width=9.2,
        ).move_to([0, 2.72, 0])
        resolution = serif_text(
            "Eight timed expansions. One continuous shaft.",
            color=WHITE_3B1B, height=0.34, italic=True,
        ).move_to([0, -2.75, 0])
        fix(finale, resolution)
        self.play(FadeIn(finale), FadeIn(resolution, shift=UP * 0.15), run_time=1.2)
        self.begin_ambient_camera_rotation(rate=0.10)
        self.wait(3.0)
        self.stop_ambient_camera_rotation()
        self.wait(0.5)
