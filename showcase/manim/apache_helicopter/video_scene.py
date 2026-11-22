from manim import *
import numpy as np
from opto.manim_bridge import (load_forge_model, math_tex, serif_text, fix, open_curve, BG,
    BLUE_3B1B, BLUE_DIM, TEAL_3B1B, YELLOW_3B1B, GOLD_3B1B, MAROON_3B1B, GREEN_3B1B,
    RED_3B1B, PURPLE_3B1B, WHITE_3B1B, MUTED_3B1B)


class OptoEpisode(ThreeDScene):
    def construct(self):
        caption = [None]

        def narrate(text):
            new = serif_text(text, color=WHITE_3B1B, height=0.27, max_width=12.6)
            new.move_to([0, -3.35, 0])
            fix(new)
            if caption[0] is None:
                self.play(FadeIn(new), run_time=0.55)
            else:
                self.play(FadeOut(caption[0]), FadeIn(new), run_time=0.65)
            caption[0] = new
            return new

        def clear(*mobs):
            group = Group(*mobs)
            fix(group)
            self.play(FadeOut(group), run_time=0.5)

        title = serif_text(
            "How does an AH-64 Apache attack helicopter work?",
            height=0.53, max_width=12.2
        ).move_to([0, 0.65, 0])
        subtitle = serif_text(
            "Twin turbines power variable-pitch rotors for lift and control.",
            color=BLUE_3B1B, height=0.30, max_width=10.5
        ).move_to([0, -0.05, 0])
        hook = serif_text(
            "How can one rotating wing both carry and steer an aircraft?",
            color=MUTED_3B1B, height=0.29, italic=True, max_width=10.0
        ).move_to([0, -0.65, 0])
        underline = Line(
            [-3.1, 0.25, 0], [3.1, 0.25, 0],
            color=BLUE_3B1B, stroke_width=2
        )
        fix(title, subtitle, hook, underline)
        self.play(FadeIn(title), Create(underline), run_time=1.0)
        self.play(FadeIn(subtitle), FadeIn(hook), run_time=0.9)
        self.wait(0.5)
        clear(title, subtitle, hook, underline)

        model = load_forge_model(self)
        model.setup_camera(ambient_rate=0.07)
        model.play_blueprint_intro()

        divider = Line(
            [0.05, -2.8, 0], [0.05, 3.25, 0],
            color=BLUE_DIM, stroke_width=1.3
        )
        fix(divider)
        self.play(*model.move_left_anims(), Create(divider), run_time=1.4)

        # Act I — the rotor is an actuator disk, not a fixed wing.
        self.play(*model.focus_anims({
            "aft_fuselage": "#7f8c99",
            "stub_wings": "#6fa8c9",
            "main_rotor_blades": "#59c9f1",
            "tail_rotor_blades": "#79d5ef",
            "landing_gear": "#d7c98b",
        }, dim_opacity=0.18), run_time=1.0)
        narrate(
            "The airframe hangs from a rotor disk: flight begins by continuously driving air downward."
        )

        rotor_center = np.array([1.65, 1.55, 0])
        disk = Circle(radius=1.05, color=BLUE_DIM, stroke_width=1.5)
        disk.scale([1, 0.43, 1]).move_to(rotor_center)
        hub = Dot(rotor_center, radius=0.055, color=YELLOW_3B1B)
        mast = Line(
            rotor_center, [1.65, -0.05, 0],
            color=MUTED_3B1B, stroke_width=2
        )
        fuselage = open_curve(
            [[0.8, -0.15, 0], [1.5, -0.05, 0],
             [2.35, -0.15, 0], [2.65, -0.35, 0]],
            color=MUTED_3B1B, stroke_width=3
        )
        thrust = Arrow(
            [1.65, -0.8, 0], [1.65, 0.05, 0], buff=0,
            color=TEAL_3B1B, stroke_width=3,
            max_tip_length_to_length_ratio=0.18
        )
        weight = Arrow(
            [2.35, -0.05, 0], [2.35, -1.0, 0], buff=0,
            color=GOLD_3B1B, stroke_width=3,
            max_tip_length_to_length_ratio=0.18
        )
        t_label = math_tex("T", color=TEAL_3B1B, height=0.36)
        t_label.next_to(thrust, LEFT, buff=0.12)
        w_label = math_tex("Mg", color=GOLD_3B1B, height=0.36)
        w_label.next_to(weight, RIGHT, buff=0.12)
        area_eq = math_tex(
            r"A=\pi R^2,\quad v_{\mathrm{tip}}=\Omega R",
            height=0.54, max_width=3.8
        ).move_to([4.75, 2.05, 0])
        hover_eq = math_tex(
            r"T=Mg\quad\Longleftrightarrow\quad\mathrm{hover}",
            height=0.52, max_width=3.8
        ).move_to([4.75, 0.95, 0])
        climb_eq = math_tex(
            r"T>Mg:\ \mathrm{climb}",
            color=TEAL_3B1B, height=0.43, max_width=3.4
        ).move_to([4.75, 0.08, 0])
        angle = ValueTracker(0)

        def rotating_blades():
            a = angle.get_value()
            p1 = rotor_center + 1.05 * np.array(
                [np.cos(a), 0.43 * np.sin(a), 0]
            )
            p2 = rotor_center - 1.05 * np.array(
                [np.cos(a), 0.43 * np.sin(a), 0]
            )
            b = a + PI / 2
            p3 = rotor_center + 1.05 * np.array(
                [np.cos(b), 0.43 * np.sin(b), 0]
            )
            p4 = rotor_center - 1.05 * np.array(
                [np.cos(b), 0.43 * np.sin(b), 0]
            )
            group = VGroup(
                open_curve(
                    [p1, p2], color=BLUE_3B1B,
                    stroke_width=3, smooth=False
                ),
                open_curve(
                    [p3, p4], color=BLUE_3B1B,
                    stroke_width=3, smooth=False
                ),
                Line(
                    rotor_center, p1,
                    color=YELLOW_3B1B, stroke_width=1.5
                )
            )
            fix(group)
            return group

        blades = always_redraw(rotating_blades)
        fix(
            disk, hub, mast, fuselage, thrust, weight, t_label, w_label,
            area_eq, hover_eq, climb_eq
        )
        self.play(
            Create(disk), Create(mast), Create(fuselage), FadeIn(hub),
            Write(area_eq), run_time=1.2
        )
        self.add(blades)
        self.play(
            Create(thrust), Create(weight), FadeIn(t_label),
            FadeIn(w_label), Write(hover_eq), run_time=1.0
        )
        self.play(
            angle.animate.set_value(5 * TAU),
            run_time=3.4, rate_func=linear
        )
        self.play(Write(climb_eq), run_time=0.8)

        rotor_callout = model.make_callout(
            "main_rotor_blades", "Four-blade main rotor",
            BLUE_3B1B, pos=[-3.6, 2.6, 0]
        )
        fix(rotor_callout)
        self.play(FadeIn(rotor_callout), run_time=0.5)
        self.wait(0.3)
        clear(
            disk, hub, mast, fuselage, thrust, weight, t_label, w_label,
            area_eq, hover_eq, climb_eq, blades, rotor_callout
        )

        # Act II — range and bearing turn sensors into a target solution.
        self.play(*model.focus_anims({
            "tads_pnvs": "#59c9f1",
            "longbow_radar": "#f5c15d",
            "tandem_cockpit": "#b68ee8",
            "hellfire_missiles": "#e49b62",
            "m230_chain_gun": "#d6d6d6",
        }, dim_opacity=0.18), run_time=1.0)
        narrate(
            "Longbow and TADS/PNVS measure direction and range, giving the crew a geometric sightline."
        )

        sensor = np.array([0.85, 1.65, 0])
        target_point = np.array([5.65, -0.65, 0])
        horizontal = DashedLine(
            sensor, [target_point[0], sensor[1], 0],
            color=MUTED_3B1B, stroke_width=1.2
        )
        vertical = DashedLine(
            [target_point[0], sensor[1], 0], target_point,
            color=MUTED_3B1B, stroke_width=1.2
        )
        sightline = DashedLine(
            sensor, target_point, color=BLUE_3B1B, stroke_width=2
        )
        sensor_dot = Dot(sensor, radius=0.06, color=GOLD_3B1B)
        target_dot = Dot(target_point, radius=0.09, color=RED_3B1B)
        lock = Circle(
            radius=0.22, color=RED_3B1B, stroke_width=2
        ).move_to(target_point)
        dx = target_point[0] - sensor[0]
        dh = sensor[1] - target_point[1]
        depression = -np.arctan2(dh, dx)
        arc = Arc(
            radius=0.72, start_angle=depression, angle=-depression,
            arc_center=sensor, color=GOLD_3B1B, stroke_width=2
        )
        eps = math_tex(r"\varepsilon", color=GOLD_3B1B, height=0.35)
        eps.move_to(sensor + [0.86, -0.28, 0])
        range_eq = math_tex(
            r"r=\sqrt{x^2+h^2}", height=0.55, max_width=3.0
        ).move_to([4.7, 2.65, 0])
        angle_eq = math_tex(
            r"\varepsilon=\tan^{-1}(h/x)", height=0.48, max_width=3.0
        ).move_to([4.7, 2.05, 0])
        scan_angle = ValueTracker(-0.85)
        ray_length = np.sqrt(dx * dx + dh * dh)

        def scanning_ray():
            a = scan_angle.get_value()
            end = sensor + ray_length * np.array(
                [np.cos(a), np.sin(a), 0]
            )
            group = VGroup(
                Line(sensor, end, color=GOLD_3B1B, stroke_width=2),
                Dot(end, radius=0.035, color=GOLD_3B1B)
            )
            fix(group)
            return group

        scan = always_redraw(scanning_ray)
        sensor_label = serif_text(
            "sensor", color=GOLD_3B1B, height=0.23
        )
        sensor_label.next_to(sensor_dot, UP, buff=0.12)
        target_label = serif_text(
            "target", color=RED_3B1B, height=0.23
        )
        target_label.next_to(target_dot, DOWN, buff=0.15)
        fix(
            horizontal, vertical, sightline, sensor_dot, target_dot, lock,
            arc, eps, range_eq, angle_eq, sensor_label, target_label
        )
        self.play(
            Create(horizontal), Create(vertical), FadeIn(sensor_dot),
            FadeIn(target_dot), FadeIn(sensor_label),
            FadeIn(target_label), Write(range_eq), run_time=1.0
        )
        self.add(scan)
        self.play(
            scan_angle.animate.set_value(depression),
            run_time=2.4, rate_func=smooth
        )
        self.remove(scan)
        self.play(
            Create(sightline), Create(arc), FadeIn(eps),
            Write(angle_eq), Create(lock), run_time=1.0
        )

        radar_callout = model.make_callout(
            "longbow_radar", "Longbow radar",
            GOLD_3B1B, pos=[-3.4, 2.6, 0]
        )
        sight_callout = model.make_callout(
            "tads_pnvs", "TADS / PNVS sightline",
            BLUE_3B1B, pos=[-3.5, -2.0, 0]
        )
        fix(radar_callout, sight_callout)
        self.play(
            FadeIn(radar_callout), FadeIn(sight_callout), run_time=0.6
        )
        self.wait(0.35)
        clear(
            horizontal, vertical, sightline, sensor_dot, target_dot,
            lock, arc, eps, range_eq, angle_eq, sensor_label,
            target_label, radar_callout, sight_callout
        )

        # Act III — the gas turbine turns fuel energy into shaft power.
        model.play_cutaway(focus={
            "engine_nacelles": "#668da6",
            "axial_compressors": "#59c9f1",
            "combustors": "#ed9950",
            "turbine_stages": "#f5c15d",
            "main_transmission": "#b68ee8",
        })
        narrate(
            "Inside each nacelle, compressed air is heated; turbine stages recover work as shaft power."
        )

        shaft_y = 1.25
        shaft = Line(
            [0.65, shaft_y, 0], [6.25, shaft_y, 0],
            color=MUTED_3B1B, stroke_width=3
        )
        comp_center = np.array([1.35, shaft_y, 0])
        turb_center = np.array([4.15, shaft_y, 0])
        comp_ring = Circle(
            radius=0.46, color=BLUE_3B1B, stroke_width=2
        ).move_to(comp_center)
        turb_ring = Circle(
            radius=0.46, color=GOLD_3B1B, stroke_width=2
        ).move_to(turb_center)
        combustor = open_curve(
            [[2.25, shaft_y, 0], [2.45, 1.65, 0], [2.68, 0.93, 0],
             [2.91, 1.61, 0], [3.18, shaft_y, 0]],
            color="#ed9950", stroke_width=4, smooth=True
        )
        transmission = Circle(
            radius=0.55, color=PURPLE_3B1B, stroke_width=2.5
        ).move_to([5.65, shaft_y, 0])
        mast_power = Arrow(
            [5.65, 1.82, 0], [5.65, 2.52, 0], buff=0,
            color=PURPLE_3B1B, stroke_width=2.5
        )
        compressor_label = serif_text(
            "axial compressor", color=BLUE_3B1B, height=0.22
        ).move_to([1.35, 0.48, 0])
        combustor_label = serif_text(
            "combustor", color="#ed9950", height=0.22
        ).move_to([2.72, 0.48, 0])
        turbine_label = serif_text(
            "turbine", color=GOLD_3B1B, height=0.22
        ).move_to([4.15, 0.48, 0])
        transmission_label = serif_text(
            "transmission", color=PURPLE_3B1B, height=0.22
        ).move_to([5.65, 0.48, 0])
        stage_labels = Group(
            compressor_label, combustor_label,
            turbine_label, transmission_label
        )
        energy_eq = math_tex(
            r"\dot m_f\,\mathrm{LHV}\ \longrightarrow\ "
            r"P_{\mathrm{shaft}}=\tau\Omega",
            height=0.55, max_width=5.6
        ).move_to([3.55, 2.85, 0])
        efficiency_eq = math_tex(
            r"\eta=\frac{P_{\mathrm{shaft}}}{\dot m_f\,\mathrm{LHV}}",
            color=TEAL_3B1B, height=0.5, max_width=3.0
        ).move_to([3.55, -0.45, 0])
        engine_phase = ValueTracker(0)

        def engine_rotors():
            a = engine_phase.get_value()
            group = VGroup()
            for center, color in (
                (comp_center, BLUE_3B1B),
                (turb_center, GOLD_3B1B)
            ):
                for offset in (0, PI / 3, 2 * PI / 3):
                    v = 0.41 * np.array(
                        [np.cos(a + offset), np.sin(a + offset), 0]
                    )
                    group.add(Line(
                        center - v, center + v,
                        color=color, stroke_width=2
                    ))
            fix(group)
            return group

        rotating_engine = always_redraw(engine_rotors)
        gas_path = open_curve(
            [[0.68, shaft_y, 0], [4.6, shaft_y, 0]],
            color=BLUE_DIM, stroke_width=1, smooth=False
        )
        gas_dot = Dot(
            [0.68, shaft_y, 0], radius=0.06, color=TEAL_3B1B
        )
        fix(
            shaft, comp_ring, turb_ring, combustor, transmission,
            mast_power, stage_labels, energy_eq, efficiency_eq,
            gas_path, gas_dot
        )
        self.play(
            Create(shaft), Create(comp_ring), Create(combustor),
            Create(turb_ring), Create(transmission),
            FadeIn(stage_labels), Write(energy_eq), run_time=1.2
        )
        self.add(rotating_engine)
        self.play(
            engine_phase.animate.set_value(7 * TAU),
            MoveAlongPath(gas_dot, gas_path),
            run_time=3.8, rate_func=linear
        )
        self.play(
            Create(mast_power), Write(efficiency_eq), run_time=0.9
        )
        transmission_callout = model.make_callout(
            "main_transmission", "Power converges here",
            PURPLE_3B1B, pos=[-3.5, 2.6, 0]
        )
        fix(transmission_callout)
        self.play(FadeIn(transmission_callout), run_time=0.5)
        self.wait(0.3)
        clear(
            shaft, comp_ring, turb_ring, combustor, transmission,
            mast_power, stage_labels, energy_eq, efficiency_eq,
            rotating_engine, gas_path, gas_dot, transmission_callout
        )

        # Act IV — collective and cyclic pitch are transmitted mechanically.
        self.play(*model.focus_anims({
            "engine_shafts": "#d6d6d6",
            "main_transmission": "#b68ee8",
            "rotor_mast": "#f5c15d",
        }, dim_opacity=0.18), run_time=0.8)
        narrate(
            "The shafts and mast transmit torque; the swashplate then decides how each blade bites the air."
        )
        self.wait(0.6)
        self.play(*model.focus_anims({
            "swashplate": "#59c9f1",
            "pitch_links_and_blade_grips": "#f5c15d",
            "main_rotor_blades": "#79d5ef",
            "tail_rotor_blades": "#79d5ef",
        }, dim_opacity=0.18), run_time=0.9)

        pitch_eq = math_tex(
            r"\theta(\psi)=\theta_0+\theta_{1c}\cos\psi+"
            r"\theta_{1s}\sin\psi",
            height=0.52, max_width=5.8
        ).move_to([3.55, 2.82, 0])
        ax = Axes(
            x_range=[0, TAU, PI / 2],
            y_range=[0, 0.32, 0.08],
            x_length=4.8, y_length=2.0, tips=False,
            axis_config={"color": MUTED_3B1B, "stroke_width": 1.2}
        ).move_to([3.75, 1.05, 0])
        pitch_curve = ax.plot(
            lambda p: 0.20 + 0.08 * np.cos(p),
            color=BLUE_3B1B, stroke_width=2.5
        )
        x_label = serif_text(
            "blade azimuth  ψ", color=MUTED_3B1B, height=0.22
        ).move_to([3.85, -0.19, 0])
        y_label = serif_text(
            "pitch  θ", color=MUTED_3B1B, height=0.22
        ).move_to([1.0, 1.85, 0])
        revolution_label = serif_text(
            "one revolution → one pitch cycle",
            color=BLUE_3B1B, height=0.22
        ).move_to([4.15, -0.46, 0])
        psi = ValueTracker(0)

        def pitch_point():
            p = psi.get_value()
            value = 0.20 + 0.08 * np.cos(p)
            point = ax.c2p(p, value)
            group = VGroup(
                Dot(point, radius=0.055, color=YELLOW_3B1B),
                Line(
                    ax.c2p(p, 0), point,
                    color=GOLD_3B1B, stroke_width=1.4
                )
            )
            fix(group)
            return group

        moving_pitch = always_redraw(pitch_point)
        plate = Circle(radius=0.45, color=BLUE_3B1B, stroke_width=2)
        plate.scale([1, 0.35, 1]).move_to([0.95, -1.35, 0])
        plate_mast = Line(
            [0.95, -1.85, 0], [0.95, -0.65, 0],
            color=MUTED_3B1B, stroke_width=2
        )

        def pitch_link():
            p = psi.get_value()
            top = -0.86 + 0.152 * np.cos(p)
            group = VGroup(
                Line(
                    [0.58, -1.48, 0], [0.58, top, 0],
                    color=GOLD_3B1B, stroke_width=2.5
                ),
                Dot(
                    [0.58, top, 0], radius=0.04, color=YELLOW_3B1B
                )
            )
            fix(group)
            return group

        animated_link = always_redraw(pitch_link)
        tail_eq = math_tex(
            r"T_{\mathrm{tail}}\,r_{\mathrm{tail}}=Q_{\mathrm{main}}",
            color=TEAL_3B1B, height=0.48, max_width=4.2
        ).move_to([4.45, -1.35, 0])
        fix(
            pitch_eq, ax, pitch_curve, x_label, y_label,
            revolution_label, plate, plate_mast, tail_eq
        )
        self.play(Write(pitch_eq), Create(ax), run_time=0.9)
        self.play(
            Create(pitch_curve), FadeIn(x_label), FadeIn(y_label),
            FadeIn(revolution_label), Create(plate),
            Create(plate_mast), run_time=0.9
        )
        self.add(moving_pitch, animated_link)
        self.play(
            psi.animate.set_value(TAU), run_time=4.4, rate_func=linear
        )
        self.play(Write(tail_eq), run_time=0.7)
        self.play(
            pitch_curve.animate.set_color(YELLOW_3B1B), run_time=0.35
        )
        self.wait(0.25)
        clear(
            pitch_eq, ax, pitch_curve, x_label, y_label,
            revolution_label, moving_pitch, plate, plate_mast,
            animated_link, tail_eq
        )

        # Act V — momentum theory closes the loop from power to lift.
        self.play(*model.focus_anims({
            "axial_compressors": "#59c9f1",
            "combustors": "#ed9950",
            "turbine_stages": "#f5c15d",
            "main_rotor_blades": "#79d5ef",
        }, dim_opacity=0.18), run_time=0.8)
        narrate(
            "The same airflow closes the story: rotor thrust is momentum flux, and hovering has an ideal power cost."
        )

        rotor_disk = Line(
            [0.65, 1.55, 0], [2.85, 1.55, 0],
            color=BLUE_3B1B, stroke_width=5
        )
        left_stream = open_curve(
            [[0.45, 2.55, 0], [0.65, 1.55, 0],
             [0.92, 0.15, 0], [1.00, -1.45, 0]],
            color=BLUE_DIM, stroke_width=1.7
        )
        right_stream = open_curve(
            [[3.05, 2.55, 0], [2.85, 1.55, 0],
             [2.58, 0.15, 0], [2.50, -1.45, 0]],
            color=BLUE_DIM, stroke_width=1.7
        )
        disk_label = math_tex(
            "A", color=BLUE_3B1B, height=0.36
        ).move_to([3.0, 1.65, 0])
        vi_label = math_tex(
            r"v_i", color=TEAL_3B1B, height=0.36
        ).move_to([1.98, 0.4, 0])
        arrows = VGroup(*[
            Arrow(
                [x, 2.35, 0], [x, 1.82, 0], buff=0,
                color=TEAL_3B1B, stroke_width=2,
                max_tip_length_to_length_ratio=0.25
            )
            for x in (1.05, 1.75, 2.45)
        ], *[
            Arrow(
                [x, 0.95, 0], [x, 0.25, 0], buff=0,
                color=TEAL_3B1B, stroke_width=2,
                max_tip_length_to_length_ratio=0.2
            )
            for x in (1.25, 1.75, 2.25)
        ])
        mass_eq = math_tex(
            r"\dot m=\rho A v_i", height=0.45, max_width=2.7
        ).move_to([4.85, 2.55, 0])
        momentum_eq = math_tex(
            r"T=\dot m(2v_i)=2\rho A v_i^2",
            height=0.45, max_width=3.3
        ).move_to([4.85, 1.65, 0])
        power_eq = math_tex(
            r"P_i=Tv_i=\frac{T^{3/2}}{\sqrt{2\rho A}}",
            color=GOLD_3B1B, height=0.48, max_width=3.3
        ).move_to([4.85, 0.65, 0])
        hover_power = math_tex(
            r"T=Mg\ \Rightarrow\ P_i=\frac{(Mg)^{3/2}}{\sqrt{2\rho A}}",
            color=TEAL_3B1B, height=0.48, max_width=4.0
        ).move_to([4.55, -1.25, 0])
        air_path = open_curve(
            [[1.75, 2.55, 0], [1.75, -1.45, 0]],
            color=BLUE_DIM, stroke_width=1, smooth=False
        )
        air_dot = Dot(
            [1.75, 2.55, 0], radius=0.065, color=TEAL_3B1B
        )
        fix(
            rotor_disk, left_stream, right_stream, disk_label, vi_label,
            arrows, mass_eq, momentum_eq, power_eq, hover_power,
            air_path, air_dot
        )
        self.play(
            Create(rotor_disk), Create(left_stream),
            Create(right_stream), Create(arrows),
            FadeIn(disk_label), FadeIn(vi_label), run_time=1.0
        )
        self.play(Write(mass_eq), run_time=0.55)
        self.play(Write(momentum_eq), run_time=0.65)
        model.play_flow(duration=3.0)
        self.play(
            MoveAlongPath(air_dot, air_path),
            run_time=2.2, rate_func=linear
        )
        self.play(Write(power_eq), run_time=0.8)
        self.play(Write(hover_power), run_time=0.9)
        self.play(
            momentum_eq.animate.set_color(YELLOW_3B1B), run_time=0.35
        )
        model.clear_flow()
        self.wait(0.35)

        # Finale — one mechanism supplies lift, attitude control, and yaw balance.
        final_formula = math_tex(
            r"P_{\mathrm{shaft}}\ \longrightarrow\ "
            r"(\Omega,\theta(\psi))\ \longrightarrow\ "
            r"(T,\mathbf{M}),\qquad T=Mg\ \mathrm{in\ hover}",
            height=0.57, max_width=9.7
        ).move_to([0, 2.75, 0])
        resolution = serif_text(
            "Turbines supply power; collective sets total lift, cyclic steers it, "
            "and the tail rotor balances torque.",
            color=WHITE_3B1B, height=0.29, max_width=10.8
        ).move_to([0, -2.75, 0])
        fix(final_formula, resolution)
        clear(
            rotor_disk, left_stream, right_stream, disk_label, vi_label,
            arrows, mass_eq, momentum_eq, power_eq, hover_power,
            air_path, air_dot, caption[0], divider
        )
        self.play(*model.focus_anims({
            "aft_fuselage": "#7f8c99",
            "stub_wings": "#6fa8c9",
            "m230_chain_gun": "#d6d6d6",
            "main_rotor_blades": "#79d5ef",
            "tail_rotor_blades": "#79d5ef",
        }, dim_opacity=0.35), run_time=0.7)
        self.play(*model.center_anims(), run_time=1.5)
        self.play(
            Write(final_formula), FadeIn(resolution), run_time=1.0
        )
        self.move_camera(
            phi=68 * DEGREES, theta=-42 * DEGREES, run_time=3.2
        )
        self.play(
            final_formula.animate.set_color(YELLOW_3B1B), run_time=0.45
        )
        self.wait(0.8)
