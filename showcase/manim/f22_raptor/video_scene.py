from manim import *
import numpy as np
from opto.manim_bridge import (
    load_forge_model, math_tex, serif_text, fix, open_curve, BG,
    BLUE_3B1B, BLUE_DIM, TEAL_3B1B, YELLOW_3B1B, GOLD_3B1B,
    MAROON_3B1B, GREEN_3B1B, RED_3B1B, PURPLE_3B1B,
    WHITE_3B1B, MUTED_3B1B
)


class OptoEpisode(ThreeDScene):
    def construct(self):
        title = serif_text(
            "How an F-22 Raptor is assembled and flies",
            height=0.50, max_width=12.4
        ).move_to([0, 0.70, 0])
        underline = Line(
            [-3.4, 0.15, 0], [3.4, 0.15, 0],
            color=BLUE_3B1B, stroke_width=2.0
        )
        hook = serif_text(
            "Stealth shaping, internal systems, twin engines and flight controls.",
            color=MUTED_3B1B, height=0.28, italic=True, max_width=10.5
        ).move_to([0, -0.32, 0])
        fix(title, underline, hook)
        self.play(FadeIn(title), run_time=0.7)
        self.play(Create(underline), FadeIn(hook), run_time=0.8)
        self.wait(0.4)

        model = load_forge_model(self)
        model.setup_camera(ambient_rate=0.07)
        self.play(FadeOut(title), FadeOut(underline), FadeOut(hook), run_time=0.5)
        model.play_blueprint_intro()

        divider = Line(
            [0.05, -2.72, 0], [0.05, 3.18, 0],
            color=BLUE_DIM, stroke_width=1.1
        )
        fix(divider)
        self.play(*model.move_left_anims(), Create(divider), run_time=1.2)

        # Act I: a rotating facet redirects its specular radar return.
        caption = serif_text(
            "Assembly begins with a shape whose edges control where radar energy goes.",
            height=0.27, max_width=12.6
        ).move_to([0, -3.35, 0])
        fix(caption)
        self.play(
            FadeIn(caption),
            *model.focus_anims({
                "forebody": BLUE_3B1B,
                "main_wings": TEAL_3B1B,
                "canted_vertical_tails": PURPLE_3B1B,
                "two_dimensional_nozzles": GOLD_3B1B,
            }),
            run_time=0.8
        )
        wing_callout = model.make_callout(
            "main_wings", "aligned wing edges", TEAL_3B1B,
            pos=[-3.9, 2.6, 0]
        )
        nozzle_callout = model.make_callout(
            "two_dimensional_nozzles", "two-dimensional nozzles", GOLD_3B1B,
            pos=[-3.8, -2.0, 0]
        )
        fix(wing_callout, nozzle_callout)
        self.play(FadeIn(wing_callout), FadeIn(nozzle_callout), run_time=0.5)

        act1_title = serif_text(
            "Stealth is geometry, not invisibility",
            height=0.31, max_width=5.9
        ).move_to([3.55, 2.78, 0])
        source = np.array([0.90, 2.10, 0.0])
        hit = np.array([2.70, 0.72, 0.0])
        incoming_direction = hit - source
        incoming_direction /= np.linalg.norm(incoming_direction)
        receiver = Dot(source, radius=0.065, color=BLUE_3B1B)
        incident = Arrow(
            source, hit, buff=0, color=BLUE_3B1B,
            stroke_width=2.2, max_tip_length_to_length_ratio=0.10
        )
        hit_dot = Dot(hit, radius=0.045, color=YELLOW_3B1B)
        facet_angle = ValueTracker(0.0)

        def reflected_geometry():
            phi = facet_angle.get_value()
            tangent = np.array([np.cos(phi), np.sin(phi), 0.0])
            normal = np.array([-np.sin(phi), np.cos(phi), 0.0])
            outgoing = (
                incoming_direction
                - 2 * np.dot(incoming_direction, normal) * normal
            )
            facet = Line(
                hit - 1.12 * tangent, hit + 1.12 * tangent,
                color=YELLOW_3B1B, stroke_width=4.0
            )
            reflected_ray = Arrow(
                hit, hit + 1.95 * outgoing, buff=0,
                color=GOLD_3B1B, stroke_width=2.2,
                max_tip_length_to_length_ratio=0.10
            )
            fix(facet, reflected_ray)
            result = VGroup(facet, reflected_ray)
            fix(result)
            return result

        reflection = always_redraw(reflected_geometry)
        angle_eq = math_tex(
            r"\theta_i=\theta_r", color=YELLOW_3B1B,
            height=0.45, max_width=1.5
        ).move_to([1.55, -0.10, 0])
        radar_eq = math_tex(
            r"P_r\propto\frac{\sigma}{R^4}",
            color=GOLD_3B1B, height=0.56, max_width=2.0
        ).move_to([5.40, 1.25, 0])
        radar_note = serif_text(
            "Shaping redirects radar backscatter.",
            color=MUTED_3B1B, height=0.21, max_width=2.45
        ).move_to([5.40, 0.40, 0])
        planform = Polygon(
            [0.90, -1.42, 0], [2.15, -0.84, 0],
            [4.35, -1.42, 0], [2.15, -2.00, 0],
            color=BLUE_3B1B, stroke_width=1.7,
            fill_color=BLUE_DIM, fill_opacity=0.16
        )
        aligned_edges = open_curve(
            [[0.90, -1.42, 0.0], [2.15, -0.84, 0.0],
             [4.35, -1.42, 0.0]],
            color=TEAL_3B1B, stroke_width=3.0, smooth=False
        )
        edge_note = serif_text(
            "Aligned edges concentrate scattering into a few directions.",
            color=TEAL_3B1B, height=0.20, max_width=4.5
        ).move_to([2.65, -2.26, 0])
        fix(
            act1_title, receiver, incident, hit_dot, reflection, angle_eq,
            radar_eq, radar_note, planform, aligned_edges, edge_note
        )
        act1 = Group(
            act1_title, receiver, incident, hit_dot, reflection, angle_eq,
            radar_eq, radar_note, planform, aligned_edges, edge_note
        )
        self.play(
            FadeIn(act1_title), FadeIn(receiver), Create(incident),
            FadeIn(hit_dot), FadeIn(reflection), Create(planform),
            Create(aligned_edges), run_time=0.9
        )
        self.play(FadeIn(angle_eq), FadeIn(radar_eq), run_time=0.8)
        self.play(
            facet_angle.animate.set_value(25 * DEGREES),
            FadeIn(radar_note), FadeIn(edge_note), run_time=1.5
        )
        self.play(
            facet_angle.animate.set_value(12 * DEGREES),
            Indicate(radar_eq, color=GOLD_3B1B), run_time=0.9
        )

        # Act II: the serpentine duct feeds the engine without exposing its fan.
        self.play(
            FadeOut(act1), FadeOut(wing_callout), FadeOut(nozzle_callout),
            FadeOut(caption), run_time=0.6
        )
        caption = serif_text(
            "Serpentine ducts feed the engines while fuel, weapons and landing gear stay enclosed.",
            height=0.27, max_width=12.6
        ).move_to([0, -3.35, 0])
        fix(caption)
        self.play(FadeIn(caption), run_time=0.3)
        model.play_cutaway(focus={
            "caret_inlet_fairings": BLUE_3B1B,
            "serpentine_inlet_ducts": TEAL_3B1B,
            "main_weapon_bay_doors": GOLD_3B1B,
            "fuselage_fuel_tanks": GREEN_3B1B,
            "retracted_main_landing_gear": MUTED_3B1B,
        })
        inlet_callout = model.make_callout(
            "serpentine_inlet_ducts", "serpentine inlet ducts", TEAL_3B1B,
            pos=[-3.8, 2.6, 0]
        )
        tank_callout = model.make_callout(
            "fuselage_fuel_tanks", "internal fuel volume", GREEN_3B1B,
            pos=[-3.8, -2.0, 0]
        )
        fix(inlet_callout, tank_callout)
        self.play(FadeIn(inlet_callout), FadeIn(tank_callout), run_time=0.5)

        act2_title = serif_text(
            "An S-duct delivers air but hides the fan face",
            height=0.31, max_width=5.9
        ).move_to([3.55, 2.78, 0])
        duct_path = open_curve(
            [[0.75, 1.32, 0.0], [1.38, 1.32, 0.0], [1.92, 1.55, 0.0],
             [2.48, 0.62, 0.0], [3.02, -0.12, 0.0], [3.70, 0.18, 0.0],
             [4.45, 0.18, 0.0]],
            color=TEAL_3B1B, stroke_width=5.0, smooth=True
        )
        intake_lips = VGroup(
            Line([0.68, 1.55, 0], [0.95, 1.55, 0],
                 color=BLUE_3B1B, stroke_width=3),
            Line([0.68, 1.09, 0], [0.95, 1.09, 0],
                 color=BLUE_3B1B, stroke_width=3)
        )
        fan_ring = Circle(
            radius=0.39, color=MUTED_3B1B, stroke_width=2.0
        ).move_to([4.48, 0.18, 0])
        fan_blades = VGroup(*[
            Line(
                [4.48, 0.18, 0],
                [4.48 + 0.31 * np.cos(a), 0.18 + 0.31 * np.sin(a), 0],
                color=MUTED_3B1B, stroke_width=1.8
            )
            for a in np.linspace(0, TAU, 7)[:-1]
        ])
        blocked_radar = DashedLine(
            [0.82, 2.02, 0], [2.82, 0.55, 0],
            color=BLUE_DIM, stroke_width=1.5
        )
        blockage = Dot([2.82, 0.55, 0], radius=0.055, color=MAROON_3B1B)
        moving_air = Dot(
            duct_path.point_from_proportion(0.0),
            radius=0.075, color=BLUE_3B1B
        )
        continuity = math_tex(
            r"\dot m=\rho A V", color=WHITE_3B1B,
            height=0.55, max_width=2.0
        ).move_to([5.40, 1.30, 0])
        area_eq = math_tex(
            r"A_1V_1\approx A_2V_2", color=TEAL_3B1B,
            height=0.45, max_width=2.2
        ).move_to([5.40, 0.48, 0])
        area_note = serif_text(
            "Approximate incompressible intake flow.",
            color=MUTED_3B1B, height=0.20, max_width=2.35
        ).move_to([5.40, -0.22, 0])
        duct_note = serif_text(
            "The bend removes a straight radar sightline to the compressor.",
            color=BLUE_3B1B, height=0.22, max_width=5.2
        ).move_to([3.35, -1.70, 0])
        fix(
            act2_title, duct_path, intake_lips, fan_ring, fan_blades,
            blocked_radar, blockage, moving_air, continuity,
            area_eq, area_note, duct_note
        )
        act2 = Group(
            act2_title, duct_path, intake_lips, fan_ring, fan_blades,
            blocked_radar, blockage, moving_air, continuity,
            area_eq, area_note, duct_note
        )
        self.play(
            FadeIn(act2_title), Create(duct_path), FadeIn(intake_lips),
            Create(fan_ring), Create(fan_blades), FadeIn(moving_air),
            run_time=0.8
        )
        self.play(
            Create(blocked_radar), FadeIn(blockage),
            FadeIn(continuity), FadeIn(duct_note), run_time=0.8
        )
        self.play(
            MoveAlongPath(moving_air, duct_path, rate_func=linear),
            FadeIn(area_eq), FadeIn(area_note), run_time=2.4
        )
        self.play(Indicate(fan_ring, color=TEAL_3B1B), run_time=0.5)

        # Act III: electronic phase delays steer the APG-77 radar beam.
        self.play(
            FadeOut(act2), FadeOut(inlet_callout), FadeOut(tank_callout),
            FadeOut(caption), run_time=0.6
        )
        caption = serif_text(
            "The APG-77 steers electronically; the cockpit and AIM-120s remain internal.",
            height=0.27, max_width=12.6
        ).move_to([0, -3.35, 0])
        fix(caption)
        self.play(
            FadeIn(caption),
            *model.focus_anims({
                "forebody": BLUE_DIM,
                "an_apg_77_aesa_radar": TEAL_3B1B,
                "cockpit_tub": GOLD_3B1B,
                "aim_120_missiles": MAROON_3B1B,
                "f119_fans": BLUE_3B1B,
            }),
            run_time=0.8
        )
        radar_callout = model.make_callout(
            "an_apg_77_aesa_radar", "AN/APG-77 AESA radar", TEAL_3B1B,
            pos=[-3.8, 2.6, 0]
        )
        missile_callout = model.make_callout(
            "aim_120_missiles", "AIM-120s in the main bay", MAROON_3B1B,
            pos=[-3.8, -2.0, 0]
        )
        fix(radar_callout, missile_callout)
        self.play(FadeIn(radar_callout), FadeIn(missile_callout), run_time=0.5)

        act3_title = serif_text(
            "A phased array turns time delays into direction",
            height=0.31, max_width=5.9
        ).move_to([3.55, 2.78, 0])
        emitter_positions = [
            np.array([1.05, y, 0.0]) for y in [-0.55, 0.28, 1.11]
        ]
        array_center = np.array([1.05, 0.28, 0.0])
        emitters = VGroup(*[
            Dot(p, radius=0.075, color=TEAL_3B1B)
            for p in emitter_positions
        ])
        array_line = Line(
            [1.05, -0.78, 0], [1.05, 1.34, 0],
            color=MUTED_3B1B, stroke_width=1.2
        )
        beam_angle = ValueTracker(-12 * DEGREES)

        def phased_beam():
            theta = beam_angle.get_value()
            direction = np.array([np.cos(theta), np.sin(theta), 0.0])
            perpendicular = np.array([-np.sin(theta), np.cos(theta), 0.0])
            ends = []
            rays = []
            for start in emitter_positions:
                distance = 2.55 - np.dot(start - array_center, direction)
                end = start + distance * direction
                ends.append(end)
                ray = Line(start, end, color=BLUE_3B1B, stroke_width=1.8)
                fix(ray)
                rays.append(ray)
            midpoint = 0.5 * (ends[0] + ends[-1])
            wavefront = Line(
                midpoint - 0.92 * perpendicular,
                midpoint + 0.92 * perpendicular,
                color=YELLOW_3B1B, stroke_width=3.2
            )
            fix(wavefront)
            result = VGroup(*rays, wavefront)
            fix(result)
            return result

        beam = always_redraw(phased_beam)
        phase_eq = math_tex(
            r"\Delta\phi=\frac{2\pi d}{\lambda}\sin\theta",
            color=YELLOW_3B1B, height=0.53, max_width=2.25
        ).move_to([5.35, 1.28, 0])
        steering_eq = math_tex(
            r"\sin\theta=\frac{\lambda\Delta\phi}{2\pi d}",
            color=TEAL_3B1B, height=0.48, max_width=2.25
        ).move_to([5.35, 0.42, 0])
        phase_note = serif_text(
            "Equal phase means constructive interference.",
            color=MUTED_3B1B, height=0.21, max_width=2.45
        ).move_to([5.35, -0.48, 0])
        spacing_line = DashedLine(
            [0.68, -0.55, 0], [0.68, 0.28, 0],
            color=MUTED_3B1B, stroke_width=1.2
        )
        spacing_label = math_tex(
            "d", height=0.34, max_width=0.5
        ).move_to([0.45, -0.14, 0])
        fix(
            act3_title, emitters, array_line, beam, phase_eq, steering_eq,
            phase_note, spacing_line, spacing_label
        )
        act3 = Group(
            act3_title, emitters, array_line, beam, phase_eq, steering_eq,
            phase_note, spacing_line, spacing_label
        )
        self.play(
            FadeIn(act3_title), Create(array_line), FadeIn(emitters),
            FadeIn(beam), FadeIn(spacing_line), FadeIn(spacing_label),
            run_time=0.8
        )
        self.play(FadeIn(phase_eq), run_time=0.7)
        self.play(
            beam_angle.animate.set_value(28 * DEGREES),
            FadeIn(steering_eq), FadeIn(phase_note), run_time=1.7
        )
        self.play(
            beam_angle.animate.set_value(10 * DEGREES),
            Indicate(steering_eq, color=TEAL_3B1B), run_time=0.9
        )

        # Act IV: a moving state traces the Brayton cycle of each F119.
        self.play(
            FadeOut(act3), FadeOut(radar_callout), FadeOut(missile_callout),
            FadeOut(caption), run_time=0.6
        )
        caption = serif_text(
            "Each F119 compresses air, adds heat, extracts turbine work and expands the exhaust.",
            height=0.27, max_width=12.6
        ).move_to([0, -3.35, 0])
        fix(caption)
        self.play(
            FadeIn(caption),
            *model.focus_anims({
                "f119_fans": BLUE_3B1B,
                "axial_compressors": TEAL_3B1B,
                "annular_combustors": GOLD_3B1B,
                "turbines": PURPLE_3B1B,
                "afterburners": MAROON_3B1B,
            }),
            run_time=0.8
        )
        fan_callout = model.make_callout(
            "f119_fans", "fan and axial compression", BLUE_3B1B,
            pos=[-3.8, 2.6, 0]
        )
        combustor_callout = model.make_callout(
            "annular_combustors", "annular combustor", GOLD_3B1B,
            pos=[-3.8, -2.0, 0]
        )
        fix(fan_callout, combustor_callout)
        self.play(FadeIn(fan_callout), FadeIn(combustor_callout), run_time=0.5)

        act4_title = serif_text(
            "The engine's Brayton cycle", height=0.31, max_width=5.9
        ).move_to([3.55, 2.78, 0])
        axes = Axes(
            x_range=[0, 5, 1], y_range=[0, 8, 2],
            x_length=3.65, y_length=3.15, tips=False,
            axis_config={"color": MUTED_3B1B, "stroke_width": 1.2}
        ).move_to([2.65, 0.05, 0])
        gamma = 1.4
        v1, p1, v2, v3, v4 = 4.0, 1.0, 1.0, 2.2, 4.0
        p2 = p1 * (v1 / v2) ** gamma
        p3 = p2
        p4 = p3 * (v3 / v4) ** gamma
        compression_points = [
            axes.coords_to_point(v, p1 * (v1 / v) ** gamma)
            for v in np.linspace(v2, v1, 28)
        ]
        heat_points = [
            axes.coords_to_point(v2, p2), axes.coords_to_point(v3, p3)
        ]
        expansion_points = [
            axes.coords_to_point(v, p3 * (v3 / v) ** gamma)
            for v in np.linspace(v3, v4, 28)
        ]
        rejection_points = [
            axes.coords_to_point(v4, p4), axes.coords_to_point(v1, p1)
        ]
        compression = open_curve(
            compression_points, color=BLUE_3B1B,
            stroke_width=2.5, smooth=False
        )
        heating = open_curve(
            heat_points, color=GOLD_3B1B,
            stroke_width=3.0, smooth=False
        )
        expansion = open_curve(
            expansion_points, color=PURPLE_3B1B,
            stroke_width=2.5, smooth=False
        )
        rejection = open_curve(
            rejection_points, color=MAROON_3B1B,
            stroke_width=2.5, smooth=False
        )
        full_cycle_points = (
            compression_points + [heat_points[-1]]
            + expansion_points + [rejection_points[-1]]
        )
        cycle_path = open_curve(
            full_cycle_points, color=WHITE_3B1B,
            stroke_width=0.8, smooth=False
        )
        cycle_area = Polygon(
            *full_cycle_points, stroke_width=0,
            fill_color=BLUE_DIM, fill_opacity=0.18
        )
        state_points = [
            axes.coords_to_point(v1, p1), axes.coords_to_point(v2, p2),
            axes.coords_to_point(v3, p3), axes.coords_to_point(v4, p4)
        ]
        states = VGroup(*[
            Dot(p, radius=0.04, color=WHITE_3B1B) for p in state_points
        ])
        cycle_dot = Dot(state_points[0], radius=0.075, color=YELLOW_3B1B)
        p_label = math_tex(
            "P", height=0.34, max_width=0.4
        ).next_to(axes, UP, buff=0.12)
        v_label = math_tex(
            "v", height=0.34, max_width=0.4
        ).next_to(axes, DOWN, buff=0.12)
        work_eq = math_tex(
            r"W_{\mathrm{net}}=\oint P\,dv=Q_{\mathrm{in}}-Q_{\mathrm{out}}",
            height=0.48, max_width=2.55
        ).move_to([5.36, 1.34, 0])
        efficiency_eq = math_tex(
            r"\eta=1-\frac{1}{r_p^{(\gamma-1)/\gamma}}",
            color=GOLD_3B1B, height=0.51, max_width=2.3
        ).move_to([5.36, 0.46, 0])
        pressure_note = serif_text(
            "Higher pressure ratio raises ideal efficiency.",
            color=MUTED_3B1B, height=0.20, max_width=2.35
        ).move_to([5.36, -0.24, 0])
        stage_note = serif_text(
            "compression | heat addition | expansion",
            color=TEAL_3B1B, height=0.20, max_width=2.55
        ).move_to([5.36, -1.15, 0])
        fix(
            act4_title, axes, compression, heating, expansion, rejection,
            cycle_path, cycle_area, states, cycle_dot, p_label, v_label,
            work_eq, efficiency_eq, pressure_note, stage_note
        )
        act4 = Group(
            act4_title, axes, compression, heating, expansion, rejection,
            cycle_path, cycle_area, states, cycle_dot, p_label, v_label,
            work_eq, efficiency_eq, pressure_note, stage_note
        )
        self.play(
            FadeIn(act4_title), Create(axes), FadeIn(p_label),
            FadeIn(v_label), FadeIn(cycle_area), run_time=0.7
        )
        self.play(
            Create(compression), Create(heating), Create(expansion),
            Create(rejection), FadeIn(states), FadeIn(cycle_dot),
            FadeIn(work_eq), run_time=1.0
        )
        self.play(
            MoveAlongPath(cycle_dot, cycle_path, rate_func=linear),
            FadeIn(efficiency_eq), FadeIn(pressure_note), FadeIn(stage_note),
            run_time=3.0
        )
        self.play(
            Indicate(heating, color=GOLD_3B1B),
            Indicate(cycle_area, color=BLUE_3B1B), run_time=0.6
        )

        # Act V: control-surface deflection changes lift and pitching moment.
        self.play(
            FadeOut(act4), FadeOut(fan_callout), FadeOut(combustor_callout),
            FadeOut(caption), run_time=0.6
        )
        caption = serif_text(
            "Fly-by-wire commands actuators; small surface motions create controlling moments.",
            height=0.27, max_width=12.6
        ).move_to([0, -3.35, 0])
        fix(caption)
        self.play(
            FadeIn(caption),
            *model.focus_anims({
                "fly_by_wire_computers": TEAL_3B1B,
                "flaperons": BLUE_3B1B,
                "horizontal_stabilators": PURPLE_3B1B,
                "rudders": GOLD_3B1B,
                "two_dimensional_nozzles": MAROON_3B1B,
            }),
            run_time=0.8
        )
        computer_callout = model.make_callout(
            "fly_by_wire_computers", "fly-by-wire computers", TEAL_3B1B,
            pos=[-3.8, 2.6, 0]
        )
        surface_callout = model.make_callout(
            "flaperons", "flaperon actuators", BLUE_3B1B,
            pos=[-3.8, -2.0, 0]
        )
        fix(computer_callout, surface_callout)
        self.play(FadeIn(computer_callout), FadeIn(surface_callout), run_time=0.5)

        act5_title = serif_text(
            "Deflection changes force; leverage changes attitude",
            height=0.31, max_width=5.9
        ).move_to([3.55, 2.78, 0])
        hinge = np.array([3.02, 0.22, 0.0])
        leading = np.array([1.05, 0.22, 0.0])
        upper = open_curve(
            [[leading[0] + 1.97 * t, 0.22 + 0.21 * np.sin(np.pi * t), 0.0]
             for t in np.linspace(0, 1, 24)],
            color=BLUE_3B1B, stroke_width=2.8, smooth=True
        )
        lower = open_curve(
            [[leading[0] + 1.97 * t, 0.22 - 0.10 * np.sin(np.pi * t), 0.0]
             for t in np.linspace(0, 1, 24)],
            color=BLUE_3B1B, stroke_width=2.0, smooth=True
        )
        hinge_dot = Dot(hinge, radius=0.055, color=YELLOW_3B1B)
        airflow = VGroup(*[
            Arrow(
                [0.60, y, 0], [1.00, y, 0], buff=0,
                color=TEAL_3B1B, stroke_width=1.5,
                max_tip_length_to_length_ratio=0.20
            )
            for y in [-0.55, 0.80, 1.48]
        ])
        delta = ValueTracker(-7 * DEGREES)

        def control_forces():
            angle = delta.get_value()
            trailing_tip = hinge + np.array([
                0.84 * np.cos(angle), -0.84 * np.sin(angle), 0.0
            ])
            trailing_edge = Line(
                hinge, trailing_tip, color=YELLOW_3B1B, stroke_width=4.0
            )
            lift = Arrow(
                [2.0, 0.20, 0],
                [2.0, 0.20 + 1.15 + 2.0 * angle, 0],
                buff=0, color=BLUE_3B1B, stroke_width=3.0,
                max_tip_length_to_length_ratio=0.12
            )
            fix(trailing_edge, lift)
            result = VGroup(trailing_edge, lift)
            fix(result)
            return result

        control_motion = always_redraw(control_forces)
        lift_label = math_tex(
            r"\Delta L", color=BLUE_3B1B, height=0.36, max_width=0.8
        ).move_to([2.28, 1.75, 0])
        delta_label = math_tex(
            r"\delta", color=YELLOW_3B1B, height=0.36, max_width=0.5
        ).move_to([3.65, -0.62, 0])
        lift_eq = math_tex(
            r"\Delta L=qSC_{L_\delta}\delta,\qquad q=\frac12\rho V^2",
            height=0.48, max_width=2.65
        ).move_to([5.25, 1.22, 0])
        moment_eq = math_tex(
            r"M=\Delta L\,\ell,\qquad \ddot\theta=\frac{M}{I}",
            color=GOLD_3B1B, height=0.49, max_width=2.45
        ).move_to([5.25, 0.35, 0])
        control_note = serif_text(
            "Sensor -> computer -> actuator -> surface",
            color=MUTED_3B1B, height=0.21, max_width=2.65
        ).move_to([5.25, -0.58, 0])
        force_eq = math_tex(
            r"\vec T+\vec L+\vec D+\vec W=m\vec a",
            color=TEAL_3B1B, height=0.50, max_width=3.0
        ).move_to([3.40, -1.78, 0])
        fix(
            act5_title, upper, lower, hinge_dot, airflow, control_motion,
            lift_label, delta_label, lift_eq, moment_eq, control_note, force_eq
        )
        act5 = Group(
            act5_title, upper, lower, hinge_dot, airflow, control_motion,
            lift_label, delta_label, lift_eq, moment_eq, control_note, force_eq
        )
        self.play(
            FadeIn(act5_title), Create(upper), Create(lower),
            FadeIn(hinge_dot), FadeIn(airflow), FadeIn(control_motion),
            run_time=0.8
        )
        self.play(
            FadeIn(lift_eq), FadeIn(lift_label), FadeIn(delta_label),
            FadeIn(control_note), run_time=0.8
        )
        self.play(
            delta.animate.set_value(18 * DEGREES),
            FadeIn(moment_eq), run_time=1.5
        )
        self.play(
            delta.animate.set_value(9 * DEGREES),
            Indicate(moment_eq, color=GOLD_3B1B), FadeIn(force_eq),
            run_time=1.0
        )

        self.play(
            FadeOut(caption), FadeOut(computer_callout),
            FadeOut(surface_callout),
            *model.focus_anims({
                "caret_inlet_fairings": BLUE_3B1B,
                "serpentine_inlet_ducts": TEAL_3B1B,
                "main_wings": BLUE_3B1B,
                "afterburners": MAROON_3B1B,
                "two_dimensional_nozzles": GOLD_3B1B,
            }),
            run_time=0.7
        )
        caption = serif_text(
            "Intake air, wing lift and nozzle thrust are one aircraft speaking in forces.",
            height=0.27, max_width=12.6
        ).move_to([0, -3.35, 0])
        flow_inlet_callout = model.make_callout(
            "caret_inlet_fairings", "intake air", BLUE_3B1B,
            pos=[-3.8, 2.6, 0]
        )
        flow_nozzle_callout = model.make_callout(
            "two_dimensional_nozzles", "thrust and vectoring", GOLD_3B1B,
            pos=[-3.8, -2.0, 0]
        )
        fix(caption, flow_inlet_callout, flow_nozzle_callout)
        self.play(
            FadeIn(caption), FadeIn(flow_inlet_callout),
            FadeIn(flow_nozzle_callout), run_time=0.5
        )
        model.play_flow(duration=2.6)
        model.clear_flow()
        self.play(Indicate(force_eq, color=TEAL_3B1B), run_time=0.5)

        # Finale: the assembled aircraft resolves the net-force balance.
        self.play(
            FadeOut(act5), FadeOut(flow_inlet_callout),
            FadeOut(flow_nozzle_callout), FadeOut(caption),
            *model.focus_anims({
                "forebody": BLUE_3B1B,
                "main_wings": TEAL_3B1B,
                "aim_120_missiles": MAROON_3B1B,
                "f119_fans": GOLD_3B1B,
                "canted_vertical_tails": PURPLE_3B1B,
            }),
            run_time=0.8
        )
        final_title = serif_text(
            "One airframe: shaped sensing, internal propulsion, computed control",
            height=0.32, max_width=8.8
        ).move_to([0, 2.85, 0])
        final_formula = math_tex(
            r"\vec F_{\mathrm{net}}=\vec T+\vec L+\vec D+\vec W=m\vec a",
            color=WHITE_3B1B, height=0.56, max_width=6.0
        ).move_to([0, -2.38, 0])
        final_caption = serif_text(
            "The Raptor flies because stealth, propulsion and control were assembled as one system.",
            color=MUTED_3B1B, height=0.27, max_width=12.6
        ).move_to([0, -3.35, 0])
        fix(final_title, final_formula, final_caption)
        self.play(
            *model.center_anims(), FadeOut(divider),
            FadeIn(final_title), FadeIn(final_formula), FadeIn(final_caption),
            run_time=1.3
        )
        self.begin_ambient_camera_rotation(rate=0.075)
        self.wait(2.8)
        self.stop_ambient_camera_rotation()
        self.play(Indicate(final_formula, color=BLUE_3B1B), run_time=0.6)
