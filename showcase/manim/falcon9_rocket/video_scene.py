from manim import *
import numpy as np
from opto.manim_bridge import (load_forge_model, math_tex, serif_text, fix, open_curve, BG,
    BLUE_3B1B, BLUE_DIM, TEAL_3B1B, YELLOW_3B1B, GOLD_3B1B, MAROON_3B1B, GREEN_3B1B,
    RED_3B1B, PURPLE_3B1B, WHITE_3B1B, MUTED_3B1B)


class OptoEpisode(ThreeDScene):
    def construct(self):
        def caption(text):
            mob = serif_text(text, color=WHITE_3B1B, height=0.27, max_width=12.6)
            mob.move_to(np.array([0.0, -3.35, 0.0]))
            fix(mob)
            return mob

        def board_title(text):
            mob = serif_text(text, color=WHITE_3B1B, height=0.30, bold=True, max_width=5.9)
            mob.move_to(np.array([3.55, 2.88, 0.0]))
            fix(mob)
            return mob

        def equation(tex, pos, color=WHITE_3B1B, height=0.52, max_width=5.6):
            mob = math_tex(tex, color=color, height=height, max_width=max_width)
            mob.move_to(np.array(pos))
            fix(mob)
            return mob

        def small_label(text, pos, color=MUTED_3B1B, height=0.21):
            mob = serif_text(text, color=color, height=height, max_width=2.6)
            mob.move_to(np.array(pos))
            fix(mob)
            return mob

        def callout(part_id, text, color, pos):
            label = model.make_callout(part_id, text, color, pos=pos)
            fix(label)
            anchor = np.array(model.anchor_2d(part_id), dtype=float)
            start = np.array(pos, dtype=float)
            start[1] += -0.16 if pos[1] > 0 else 0.16
            leader = open_curve(
                [start, np.array([start[0], anchor[1], 0.0]), anchor],
                color=color, stroke_width=1.2, smooth=False
            )
            fix(leader)
            return label, leader

        title = serif_text("SpaceX Falcon 9", color=WHITE_3B1B, height=0.72, bold=True)
        title.move_to(np.array([0.0, 0.35, 0.0]))
        subtitle = serif_text(
            "Two stages, nine Merlins, and a reusable booster.",
            color=MUTED_3B1B, height=0.30, italic=True
        )
        subtitle.move_to(np.array([0.0, -0.48, 0.0]))
        underline = Line(
            LEFT * 2.4, RIGHT * 2.4,
            color=BLUE_3B1B, stroke_width=2.0
        )
        underline.move_to(np.array([0.0, -0.10, 0.0]))
        fix(title, subtitle, underline)
        self.play(
            FadeIn(title),
            Create(underline),
            FadeIn(subtitle),
            run_time=1.7
        )
        self.wait(0.7)
        self.play(FadeOut(Group(title, subtitle, underline)), run_time=0.7)

        model = load_forge_model(self)
        model.setup_camera(ambient_rate=0.07)
        model.play_blueprint_intro()

        divider = Line(
            np.array([0.05, -2.85, 0.0]),
            np.array([0.05, 3.20, 0.0]),
            color=BLUE_DIM,
            stroke_width=1.2
        )
        fix(divider)
        narration = caption(
            "The rocket equation rewards shedding mass—but reusability asks us to bring mass home."
        )
        self.play(
            *model.move_left_anims(),
            Create(divider),
            FadeIn(narration),
            *model.focus_anims({
                "first_stage_airframe": BLUE_3B1B,
                "second_stage_airframe": TEAL_3B1B,
                "merlin_engines": GOLD_3B1B,
                "payload_fairing": PURPLE_3B1B
            }),
            run_time=1.4
        )

        # ACT I — Structure and the rocket equation.
        act1_title = board_title("A rocket is a sequence of mass fractions")
        fairing_call, fairing_lead = callout(
            "payload_fairing",
            "Payload fairing",
            PURPLE_3B1B,
            (-4.5, 2.6, 0.0)
        )
        engine_call, engine_lead = callout(
            "merlin_engines",
            "Nine Merlin engines",
            GOLD_3B1B,
            (-3.8, -2.0, 0.0)
        )

        stage1 = Polygon(
            np.array([0.75, -1.85, 0.0]),
            np.array([1.45, -1.85, 0.0]),
            np.array([1.45, 0.85, 0.0]),
            np.array([0.75, 0.85, 0.0]),
            color=BLUE_3B1B,
            stroke_width=2.0
        )
        stage2 = Polygon(
            np.array([0.82, 0.95, 0.0]),
            np.array([1.38, 0.95, 0.0]),
            np.array([1.38, 1.55, 0.0]),
            np.array([0.82, 1.55, 0.0]),
            color=TEAL_3B1B,
            stroke_width=2.0
        )
        fairing = Polygon(
            np.array([0.82, 1.58, 0.0]),
            np.array([1.38, 1.58, 0.0]),
            np.array([1.10, 2.35, 0.0]),
            color=PURPLE_3B1B,
            stroke_width=2.0
        )
        fix(stage1, stage2, fairing)
        s1_label = small_label(
            "Stage 1: most of the mass",
            (1.85, -0.55, 0.0),
            BLUE_3B1B,
            0.19
        )
        s2_label = small_label(
            "Stage 2",
            (1.95, 1.15, 0.0),
            TEAL_3B1B,
            0.19
        )
        brace = Brace(stage1, RIGHT, color=BLUE_DIM, stroke_width=1.3)
        fix(brace)

        rocket_eq = equation(
            r"\Delta v=v_e\ln\left(\frac{m_0}{m_f}\right)",
            (4.40, 2.15, 0.0),
            height=0.56
        )
        ax1 = Axes(
            x_range=[1.0, 4.0, 1.0],
            y_range=[0.0, 1.5, 0.5],
            x_length=3.65,
            y_length=2.45,
            axis_config={"color": BLUE_DIM, "stroke_width": 1.2},
            tips=False
        )
        ax1.move_to(np.array([4.35, 0.05, 0.0]))
        fix(ax1)
        xlabel = equation(
            r"R=m_0/m_f",
            (5.70, -1.40, 0.0),
            MUTED_3B1B,
            0.30,
            1.6
        )
        ylabel = equation(
            r"\Delta v/v_e",
            (2.45, 0.10, 0.0),
            MUTED_3B1B,
            0.30,
            1.3
        )
        ylabel.rotate(PI / 2)
        log_curve = ax1.plot(
            lambda r: np.log(r),
            x_range=[1.0, 4.0],
            color=YELLOW_3B1B
        )
        fix(log_curve)
        ratio = ValueTracker(1.15)

        def ratio_dot():
            r = ratio.get_value()
            point = ax1.coords_to_point(r, np.log(r))
            dot = Dot(point, radius=0.075, color=YELLOW_3B1B)
            fix(dot)
            return dot

        def ratio_drop():
            r = ratio.get_value()
            point = ax1.coords_to_point(r, np.log(r))
            base = ax1.coords_to_point(r, 0.0)
            line = DashedLine(
                point,
                base,
                color=MUTED_3B1B,
                stroke_width=1.1,
                dash_length=0.08
            )
            fix(line)
            return line

        moving_ratio = always_redraw(ratio_dot)
        moving_drop = always_redraw(ratio_drop)
        act1 = Group(
            act1_title,
            fairing_call,
            fairing_lead,
            engine_call,
            engine_lead,
            stage1,
            stage2,
            fairing,
            s1_label,
            s2_label,
            brace,
            rocket_eq,
            ax1,
            xlabel,
            ylabel,
            log_curve,
            moving_ratio,
            moving_drop
        )
        self.play(
            FadeIn(act1_title),
            FadeIn(fairing_call),
            Create(fairing_lead),
            FadeIn(engine_call),
            Create(engine_lead),
            LaggedStart(
                Create(stage1),
                Create(stage2),
                Create(fairing),
                lag_ratio=0.25
            ),
            FadeIn(s1_label),
            FadeIn(s2_label),
            Create(brace),
            run_time=1.8
        )
        self.play(
            Write(rocket_eq),
            Create(ax1),
            FadeIn(xlabel),
            FadeIn(ylabel),
            run_time=1.2
        )
        self.play(
            Create(log_curve),
            FadeIn(moving_ratio),
            FadeIn(moving_drop),
            run_time=1.0
        )
        self.play(ratio.animate.set_value(3.85), run_time=2.2)
        self.play(Indicate(brace, color=BLUE_3B1B), run_time=0.6)
        self.wait(0.4)

        # ACT II — Propellants, turbopumps, and the Octaweb.
        new_narration = caption(
            "LOX and RP-1 do not simply burn: turbopumps meter them into nine Merlins."
        )
        self.play(
            FadeOut(act1),
            ReplacementTransform(narration, new_narration),
            run_time=0.8
        )
        narration = new_narration
        model.play_cutaway(focus={
            "stage_1_lox_tank": "#72d9ff",
            "stage_1_rp_1_tank": "#e6a34b",
            "helium_copvs": PURPLE_3B1B,
            "lox_downcomers": BLUE_3B1B
        })

        act2_title = board_title("Propellant becomes shaft power, then thrust")
        lox_call, lox_lead = callout(
            "stage_1_lox_tank",
            "Liquid oxygen",
            "#72d9ff",
            (-4.6, 2.6, 0.0)
        )
        rp_call, rp_lead = callout(
            "stage_1_rp_1_tank",
            "RP-1 + helium COPVs",
            "#e6a34b",
            (-4.6, -2.0, 0.0)
        )
        mix_eq = equation(
            r"\frac{\dot m_{\mathrm{LOX}}}{\dot m_{\mathrm{RP-1}}}\approx2.56",
            (3.25, 2.20, 0.0),
            height=0.46
        )
        lox_bar = open_curve(
            [
                np.array([0.75, 1.43, 0.0]),
                np.array([3.55, 1.43, 0.0])
            ],
            color="#72d9ff",
            stroke_width=9.0,
            smooth=False
        )
        rp_bar = open_curve(
            [
                np.array([0.75, 0.85, 0.0]),
                np.array([1.85, 0.85, 0.0])
            ],
            color="#e6a34b",
            stroke_width=9.0,
            smooth=False
        )
        lox_label = small_label(
            "Oxidizer flow",
            (1.45, 1.78, 0.0),
            "#72d9ff"
        )
        rp_label = small_label(
            "Fuel flow",
            (1.20, 0.47, 0.0),
            "#e6a34b"
        )
        pump_center = np.array([3.25, 0.15, 0.0])
        pump = Circle(
            radius=0.38,
            color=PURPLE_3B1B,
            stroke_width=2.0
        ).move_to(pump_center)
        pump_label = small_label(
            "Turbopump",
            (3.25, -0.52, 0.0),
            PURPLE_3B1B
        )
        lox_channel = open_curve(
            [
                np.array([3.55, 1.43, 0.0]),
                np.array([3.25, 0.53, 0.0])
            ],
            color="#72d9ff",
            stroke_width=2.0,
            smooth=False
        )
        rp_channel = open_curve(
            [
                np.array([1.85, 0.85, 0.0]),
                np.array([2.87, 0.15, 0.0])
            ],
            color="#e6a34b",
            stroke_width=2.0,
            smooth=False
        )
        fix(
            mix_eq,
            lox_bar,
            rp_bar,
            lox_label,
            rp_label,
            pump,
            pump_label,
            lox_channel,
            rp_channel
        )

        octaweb_center = np.array([5.35, 0.55, 0.0])
        octaweb = Circle(
            radius=1.05,
            color=BLUE_DIM,
            stroke_width=1.5
        ).move_to(octaweb_center)
        fix(octaweb)
        engines = []
        for k in range(9):
            angle = TAU * (k - 1) / 8.0
            if k == 0:
                position = octaweb_center.copy()
            else:
                position = octaweb_center + 0.72 * np.array([
                    np.cos(angle),
                    np.sin(angle),
                    0.0
                ])
            nozzle = Circle(
                radius=0.13,
                color=GOLD_3B1B,
                stroke_width=2.3
            ).move_to(position)
            fix(nozzle)
            engines.append(nozzle)
        octa_label = small_label(
            "Octaweb: 8 around 1",
            (5.35, -0.85, 0.0),
            GOLD_3B1B
        )
        thrust_eq = equation(
            r"F=\dot m v_e+(p_e-p_a)A_e",
            (4.35, -1.62, 0.0),
            GOLD_3B1B,
            0.48,
            4.7
        )
        feed_arrow = Arrow(
            np.array([3.65, 0.15, 0.0]),
            np.array([4.35, 0.42, 0.0]),
            buff=0.0,
            color=PURPLE_3B1B,
            stroke_width=2.0,
            max_tip_length_to_length_ratio=0.20
        )
        fix(feed_arrow)
        flow_clock = ValueTracker(0.0)
        rotor_clock = ValueTracker(0.0)

        def rotor():
            angle = rotor_clock.get_value()
            offset = 0.29 * np.array([
                np.cos(angle),
                np.sin(angle),
                0.0
            ])
            line = Line(
                pump_center + offset,
                pump_center - offset,
                color=WHITE_3B1B,
                stroke_width=2.0
            )
            fix(line)
            return line

        def flowing_lox_dot():
            fraction = flow_clock.get_value() % 1.0
            point = np.array([0.82 + 2.63 * fraction, 1.43, 0.0])
            dot = Dot(point, radius=0.065, color=WHITE_3B1B)
            fix(dot)
            return dot

        def flowing_rp_dot():
            fraction = (flow_clock.get_value() + 0.4) % 1.0
            point = np.array([0.82 + 0.96 * fraction, 0.85, 0.0])
            dot = Dot(point, radius=0.065, color=WHITE_3B1B)
            fix(dot)
            return dot

        rotor_mob = always_redraw(rotor)
        lox_dot = always_redraw(flowing_lox_dot)
        rp_dot = always_redraw(flowing_rp_dot)
        tank_geometry = Group(
            act2_title,
            lox_call,
            lox_lead,
            rp_call,
            rp_lead,
            mix_eq,
            lox_bar,
            rp_bar,
            lox_label,
            rp_label
        )
        self.play(FadeIn(tank_geometry), run_time=1.2)
        self.play(
            Create(lox_channel),
            Create(rp_channel),
            Create(pump),
            FadeIn(pump_label),
            Create(octaweb),
            LaggedStart(
                *[Create(engine) for engine in engines],
                lag_ratio=0.08
            ),
            FadeIn(octa_label),
            Create(feed_arrow),
            Write(thrust_eq),
            FadeIn(rotor_mob),
            FadeIn(lox_dot),
            FadeIn(rp_dot),
            *model.focus_anims({
                "merlin_turbopumps": PURPLE_3B1B,
                "merlin_engines": GOLD_3B1B,
                "octaweb": BLUE_3B1B,
                "lox_downcomers": "#72d9ff",
                "rp_1_feed_lines": "#e6a34b"
            }),
            run_time=1.7
        )
        # play_flow performs its own scene animation and returns None.
        # It must never be passed as an argument to self.play().
        self.play(
            flow_clock.animate.set_value(1.5),
            rotor_clock.animate.set_value(2.5 * TAU),
            run_time=0.8
        )
        model.play_flow(duration=3.0)
        self.play(
            flow_clock.animate.set_value(4.5),
            rotor_clock.animate.set_value(7.5 * TAU),
            run_time=0.7
        )
        model.clear_flow()
        self.wait(0.4)
        act2 = Group(
            tank_geometry,
            lox_channel,
            rp_channel,
            pump,
            pump_label,
            octaweb,
            *engines,
            octa_label,
            thrust_eq,
            feed_arrow,
            rotor_mob,
            lox_dot,
            rp_dot
        )

        # ACT III — Separation, staging, and gimballed vacuum propulsion.
        new_narration = caption(
            "Pneumatic separators discard the empty booster; one vacuum Merlin takes over."
        )
        self.play(
            FadeOut(act2),
            ReplacementTransform(narration, new_narration),
            run_time=0.8
        )
        narration = new_narration
        self.play(
            *model.focus_anims({
                "interstage": BLUE_3B1B,
                "pneumatic_stage_separators": WHITE_3B1B,
                "merlin_vacuum_engine": TEAL_3B1B,
                "gimbal_actuators": GOLD_3B1B
            }),
            run_time=0.8
        )
        act3_title = board_title("Staging multiplies the rocket equation")
        inter_call, inter_lead = callout(
            "interstage",
            "Interstage + pneumatic separation",
            BLUE_3B1B,
            (-4.4, 2.6, 0.0)
        )
        stage_sum = equation(
            r"\Delta v_{\mathrm{tot}}=v_{e1}\ln R_1+v_{e2}\ln R_2",
            (4.15, 2.20, 0.0),
            height=0.48
        )
        sep_lower = Rectangle(
            width=0.55,
            height=1.20,
            color=BLUE_3B1B,
            stroke_width=2.0
        )
        sep_lower.move_to(np.array([1.15, 0.10, 0.0]))
        sep_upper = Rectangle(
            width=0.48,
            height=0.72,
            color=TEAL_3B1B,
            stroke_width=2.0
        )
        sep_upper.move_to(np.array([1.15, 1.08, 0.0]))
        sep_nozzle = open_curve(
            [
                np.array([0.93, 0.69, 0.0]),
                np.array([1.15, 0.48, 0.0]),
                np.array([1.37, 0.69, 0.0])
            ],
            color=GOLD_3B1B,
            stroke_width=2.0,
            smooth=False
        )
        fix(sep_lower, sep_upper, sep_nozzle)
        sep_label = small_label(
            "Mass discarded",
            (1.30, -0.78, 0.0),
            BLUE_3B1B
        )

        ax3 = Axes(
            x_range=[1.0, 3.5, 1.0],
            y_range=[0.0, 2.3, 0.5],
            x_length=3.7,
            y_length=2.3,
            tips=False,
            axis_config={"color": BLUE_DIM, "stroke_width": 1.1}
        )
        ax3.move_to(np.array([4.35, 0.48, 0.0]))
        fix(ax3)
        r1, r2 = 2.0, 3.15
        curve1 = open_curve(
            [
                ax3.coords_to_point(r, np.log(r))
                for r in np.linspace(1.0, r1, 35)
            ],
            color=BLUE_3B1B,
            stroke_width=3.0
        )
        curve2 = open_curve(
            [
                ax3.coords_to_point(
                    r,
                    np.log(r1) + 1.08 * np.log(r)
                )
                for r in np.linspace(1.0, r2, 40)
            ],
            color=TEAL_3B1B,
            stroke_width=3.0
        )
        fix(curve1, curve2)
        sr1, sr2 = ValueTracker(1.0), ValueTracker(1.0)

        def staged_dot_1():
            r = sr1.get_value()
            dot = Dot(
                ax3.coords_to_point(r, np.log(r)),
                radius=0.065,
                color=BLUE_3B1B
            )
            fix(dot)
            return dot

        def staged_dot_2():
            r = sr2.get_value()
            point = ax3.coords_to_point(
                r,
                np.log(r1) + 1.08 * np.log(r)
            )
            dot = Dot(point, radius=0.065, color=TEAL_3B1B)
            fix(dot)
            return dot

        sd1 = always_redraw(staged_dot_1)
        sd2 = always_redraw(staged_dot_2)
        stage1_tag = small_label(
            "Boost",
            (3.10, 1.45, 0.0),
            BLUE_3B1B,
            0.18
        )
        stage2_tag = small_label(
            "Vacuum",
            (5.55, 1.67, 0.0),
            TEAL_3B1B,
            0.18
        )

        gimbal_angle = ValueTracker(0.0)
        gimbal_base = np.array([4.80, -2.05, 0.0])

        def thrust_vector():
            angle = gimbal_angle.get_value()
            vector = 1.05 * np.array([
                np.sin(angle),
                np.cos(angle),
                0.0
            ])
            arrow = Arrow(
                gimbal_base,
                gimbal_base + vector,
                buff=0.0,
                color=GOLD_3B1B,
                stroke_width=2.5,
                max_tip_length_to_length_ratio=0.18
            )
            fix(arrow)
            return arrow

        def gimbal_x():
            angle = gimbal_angle.get_value()
            end = gimbal_base + 1.05 * np.array([
                np.sin(angle),
                0.0,
                0.0
            ])
            line = Line(
                gimbal_base,
                end,
                color=RED_3B1B,
                stroke_width=1.8
            )
            fix(line)
            return line

        thrust_arrow = always_redraw(thrust_vector)
        side_component = always_redraw(gimbal_x)
        gimbal_eq = equation(
            r"T_x=T\sin\theta,\qquad T_y=T\cos\theta",
            (2.45, -1.82, 0.0),
            GOLD_3B1B,
            0.37,
            3.1
        )
        self.play(
            FadeIn(act3_title),
            FadeIn(inter_call),
            Create(inter_lead),
            Create(sep_lower),
            Create(sep_upper),
            Create(sep_nozzle),
            Write(stage_sum),
            run_time=1.3
        )
        self.play(
            sep_lower.animate.shift(DOWN * 0.50),
            sep_upper.animate.shift(UP * 0.30),
            FadeIn(sep_label),
            run_time=1.0
        )
        self.play(
            Create(ax3),
            FadeIn(stage1_tag),
            FadeIn(stage2_tag),
            run_time=0.8
        )
        self.play(
            Create(curve1),
            FadeIn(sd1),
            sr1.animate.set_value(r1),
            run_time=1.6
        )
        self.play(
            Create(curve2),
            FadeIn(sd2),
            sr2.animate.set_value(r2),
            run_time=1.8
        )
        self.play(
            Write(gimbal_eq),
            FadeIn(thrust_arrow),
            FadeIn(side_component),
            run_time=0.8
        )
        self.play(gimbal_angle.animate.set_value(0.38), run_time=0.9)
        self.play(gimbal_angle.animate.set_value(-0.30), run_time=0.9)
        self.play(gimbal_angle.animate.set_value(0.0), run_time=0.6)
        act3 = Group(
            act3_title,
            inter_call,
            inter_lead,
            stage_sum,
            sep_lower,
            sep_upper,
            sep_nozzle,
            sep_label,
            ax3,
            curve1,
            curve2,
            sd1,
            sd2,
            stage1_tag,
            stage2_tag,
            thrust_arrow,
            side_component,
            gimbal_eq
        )

        # ACT IV — Fairing deployment and orbital energy.
        new_narration = caption(
            "The avionics ring closes the guidance loop while the second stage builds orbital speed."
        )
        self.play(
            FadeOut(act3),
            ReplacementTransform(narration, new_narration),
            run_time=0.8
        )
        narration = new_narration
        self.play(
            *model.focus_anims({
                "flight_computers": GREEN_3B1B,
                "avionics_ring": BLUE_3B1B,
                "payload_fairing": PURPLE_3B1B,
                "payload": TEAL_3B1B,
                "payload_attach_fitting": GOLD_3B1B
            }),
            run_time=0.8
        )
        act4_title = board_title(
            "Orbit is sideways motion, continuously falling"
        )
        payload_call, payload_lead = callout(
            "payload",
            "Payload + attach fitting",
            TEAL_3B1B,
            (-4.4, 2.6, 0.0)
        )
        fair_left = open_curve(
            [
                np.array([0.90, -0.20, 0.0]),
                np.array([0.82, 1.10, 0.0]),
                np.array([1.28, 1.75, 0.0])
            ],
            color=PURPLE_3B1B,
            stroke_width=3.0
        )
        fair_right = open_curve(
            [
                np.array([1.66, -0.20, 0.0]),
                np.array([1.74, 1.10, 0.0]),
                np.array([1.28, 1.75, 0.0])
            ],
            color=PURPLE_3B1B,
            stroke_width=3.0
        )
        payload_body = Rectangle(
            width=0.34,
            height=0.86,
            color=TEAL_3B1B,
            stroke_width=2.0
        )
        payload_body.move_to(np.array([1.28, 0.47, 0.0]))
        paf = Line(
            np.array([0.98, -0.20, 0.0]),
            np.array([1.58, -0.20, 0.0]),
            color=GOLD_3B1B,
            stroke_width=4.0
        )
        fix(fair_left, fair_right, payload_body, paf)
        deploy_label = small_label(
            "Fairing deployment",
            (1.28, -0.72, 0.0),
            PURPLE_3B1B
        )

        orbit_center = np.array([4.35, 0.15, 0.0])
        a_orbit, b_orbit = 1.85, 1.10
        c_orbit = np.sqrt(a_orbit**2 - b_orbit**2)
        earth_center = orbit_center - np.array([c_orbit, 0.0, 0.0])
        earth = Circle(
            radius=0.37,
            color=BLUE_3B1B,
            stroke_width=2.5
        ).move_to(earth_center)
        earth_dot = Dot(
            earth_center,
            radius=0.20,
            color=BLUE_DIM
        )
        orbit_path = ParametricFunction(
            lambda t: orbit_center + np.array([
                a_orbit * np.cos(t),
                b_orbit * np.sin(t),
                0.0
            ]),
            t_range=[0.0, TAU],
            color=MUTED_3B1B,
            stroke_width=1.7
        )
        fix(earth, earth_dot, orbit_path)
        orbit_phase = ValueTracker(0.25)

        def orbital_position():
            phase = orbit_phase.get_value()
            return orbit_center + np.array([
                a_orbit * np.cos(phase),
                b_orbit * np.sin(phase),
                0.0
            ])

        def satellite_dot():
            dot = Dot(
                orbital_position(),
                radius=0.085,
                color=TEAL_3B1B
            )
            fix(dot)
            return dot

        def radius_line():
            line = DashedLine(
                earth_center,
                orbital_position(),
                color=BLUE_DIM,
                stroke_width=1.0,
                dash_length=0.08
            )
            fix(line)
            return line

        def velocity_vector():
            phase = orbit_phase.get_value()
            point = orbital_position()
            tangent = np.array([
                -a_orbit * np.sin(phase),
                b_orbit * np.cos(phase),
                0.0
            ])
            tangent /= np.linalg.norm(tangent)
            radius = np.linalg.norm(point - earth_center)
            speed = np.sqrt(
                max(0.001, 2.0 / radius - 1.0 / a_orbit)
            )
            arrow = Arrow(
                point,
                point + 0.62 * speed * tangent,
                buff=0.0,
                color=YELLOW_3B1B,
                stroke_width=2.0,
                max_tip_length_to_length_ratio=0.20
            )
            fix(arrow)
            return arrow

        satellite = always_redraw(satellite_dot)
        radius_vec = always_redraw(radius_line)
        velocity_vec = always_redraw(velocity_vector)
        vis_viva = equation(
            r"v=\sqrt{\mu\left(\frac{2}{r}-\frac{1}{a}\right)}",
            (4.25, -1.72, 0.0),
            YELLOW_3B1B,
            0.50,
            4.1
        )
        speed_note = small_label(
            "Faster near Earth",
            (4.30, -2.20, 0.0),
            MUTED_3B1B,
            0.19
        )
        self.play(
            FadeIn(act4_title),
            FadeIn(payload_call),
            Create(payload_lead),
            Create(fair_left),
            Create(fair_right),
            Create(payload_body),
            Create(paf),
            FadeIn(deploy_label),
            run_time=1.2
        )
        self.play(
            fair_left.animate.rotate(
                -0.40,
                about_point=np.array([0.90, -0.20, 0.0])
            ),
            fair_right.animate.rotate(
                0.40,
                about_point=np.array([1.66, -0.20, 0.0])
            ),
            run_time=1.0
        )
        self.play(
            Create(orbit_path),
            Create(earth),
            FadeIn(earth_dot),
            FadeIn(satellite),
            FadeIn(radius_vec),
            FadeIn(velocity_vec),
            Write(vis_viva),
            FadeIn(speed_note),
            run_time=1.2
        )
        self.play(
            orbit_phase.animate.set_value(TAU + 0.25),
            run_time=3.6
        )
        act4 = Group(
            act4_title,
            payload_call,
            payload_lead,
            fair_left,
            fair_right,
            payload_body,
            paf,
            deploy_label,
            earth,
            earth_dot,
            orbit_path,
            satellite,
            radius_vec,
            velocity_vec,
            vis_viva,
            speed_note
        )

        # ACT V — Aerodynamic guidance and the terminal landing burn.
        new_narration = caption(
            "Cold gas orients the booster; grid fins steer it; reserved propellant cancels its velocity."
        )
        self.play(
            FadeOut(act4),
            ReplacementTransform(narration, new_narration),
            run_time=0.8
        )
        narration = new_narration
        self.play(
            *model.focus_anims({
                "cold_gas_thrusters": "#72d9ff",
                "titanium_grid_fins": GOLD_3B1B,
                "grid_fin_actuators": PURPLE_3B1B,
                "landing_legs": WHITE_3B1B,
                "merlin_engines": "#ff874d"
            }),
            run_time=0.8
        )
        act5_title = board_title(
            "Recovery spends a carefully reserved Δv"
        )
        fin_call, fin_lead = callout(
            "titanium_grid_fins",
            "Grid fins + cold gas",
            GOLD_3B1B,
            (-4.5, 2.6, 0.0)
        )
        leg_call, leg_lead = callout(
            "landing_legs",
            "Landing legs",
            WHITE_3B1B,
            (-4.2, -2.0, 0.0)
        )
        ax5 = Axes(
            x_range=[0.0, 4.0, 1.0],
            y_range=[0.0, 3.0, 1.0],
            x_length=3.55,
            y_length=2.75,
            tips=False,
            axis_config={"color": BLUE_DIM, "stroke_width": 1.1}
        )
        ax5.move_to(np.array([4.45, 0.20, 0.0]))
        fix(ax5)
        h_label = equation(
            r"h",
            (6.15, -1.20, 0.0),
            MUTED_3B1B,
            0.32,
            0.5
        )
        v_label = equation(
            r"v",
            (2.72, 1.36, 0.0),
            MUTED_3B1B,
            0.32,
            0.5
        )
        h0, v0 = 3.5, 2.65
        descent_curve = open_curve(
            [
                ax5.coords_to_point(h, v0 * np.sqrt(h / h0))
                for h in np.linspace(0.001, h0, 60)
            ],
            color=GOLD_3B1B,
            stroke_width=3.0
        )
        fix(descent_curve)
        landing_h = ValueTracker(h0)

        def descent_point():
            h = max(0.001, landing_h.get_value())
            velocity = v0 * np.sqrt(h / h0)
            dot = Dot(
                ax5.coords_to_point(h, velocity),
                radius=0.075,
                color=GOLD_3B1B
            )
            fix(dot)
            return dot

        def altitude_guide():
            h = max(0.001, landing_h.get_value())
            velocity = v0 * np.sqrt(h / h0)
            point = ax5.coords_to_point(h, velocity)
            base = ax5.coords_to_point(h, 0.0)
            line = DashedLine(
                point,
                base,
                color=MUTED_3B1B,
                stroke_width=1.0,
                dash_length=0.07
            )
            fix(line)
            return line

        descent_dot = always_redraw(descent_point)
        altitude_line = always_redraw(altitude_guide)
        landing_eq = equation(
            r"h_b=\frac{v_0^2}{2(T/m-g)},\qquad T>mg",
            (4.20, -1.74, 0.0),
            GOLD_3B1B,
            0.43,
            4.6
        )

        def returning_booster():
            h = landing_h.get_value()
            y = -1.65 + 2.55 * h / h0
            body = open_curve(
                [
                    np.array([1.20, y, 0.0]),
                    np.array([1.20, y + 0.65, 0.0])
                ],
                color=BLUE_3B1B,
                stroke_width=8.0,
                smooth=False
            )
            flame_length = 0.12 + 0.45 * h / h0
            flame = open_curve(
                [
                    np.array([1.20, y - 0.06, 0.0]),
                    np.array([1.20, y - flame_length, 0.0])
                ],
                color="#ff874d",
                stroke_width=5.0,
                smooth=False
            )
            thrust = Arrow(
                np.array([1.65, y + 0.05, 0.0]),
                np.array([1.65, y + 0.65, 0.0]),
                buff=0.0,
                color=GOLD_3B1B,
                stroke_width=2.0,
                max_tip_length_to_length_ratio=0.22
            )
            fix(body, flame, thrust)
            return Group(body, flame, thrust)

        booster = always_redraw(returning_booster)
        landing_pad = Line(
            np.array([0.70, -1.72, 0.0]),
            np.array([1.90, -1.72, 0.0]),
            color=WHITE_3B1B,
            stroke_width=3.0
        )
        left_leg = open_curve(
            [
                np.array([1.20, -1.35, 0.0]),
                np.array([0.92, -1.70, 0.0])
            ],
            color=WHITE_3B1B,
            stroke_width=2.0,
            smooth=False
        )
        right_leg = open_curve(
            [
                np.array([1.20, -1.35, 0.0]),
                np.array([1.48, -1.70, 0.0])
            ],
            color=WHITE_3B1B,
            stroke_width=2.0,
            smooth=False
        )
        fix(landing_pad, left_leg, right_leg)
        burn_label = small_label(
            "Constant-net-deceleration burn",
            (4.25, 2.08, 0.0),
            GOLD_3B1B,
            0.19
        )
        self.play(
            FadeIn(act5_title),
            FadeIn(fin_call),
            Create(fin_lead),
            FadeIn(leg_call),
            Create(leg_lead),
            Create(ax5),
            FadeIn(h_label),
            FadeIn(v_label),
            FadeIn(burn_label),
            Create(landing_pad),
            Create(left_leg),
            Create(right_leg),
            run_time=1.2
        )
        self.play(
            Create(descent_curve),
            FadeIn(descent_dot),
            FadeIn(altitude_line),
            FadeIn(booster),
            Write(landing_eq),
            run_time=1.0
        )
        self.play(
            landing_h.animate.set_value(0.03),
            run_time=4.2,
            rate_func=linear
        )
        self.play(
            Indicate(landing_pad, color=GREEN_3B1B),
            run_time=0.6
        )
        act5 = Group(
            act5_title,
            fin_call,
            fin_lead,
            leg_call,
            leg_lead,
            ax5,
            h_label,
            v_label,
            descent_curve,
            descent_dot,
            altitude_line,
            landing_eq,
            booster,
            landing_pad,
            left_leg,
            right_leg,
            burn_label
        )

        # Finale — The two jobs of Falcon 9's propellant budget.
        final_narration = caption(
            "Staging delivers the payload; guidance and reserved Δv bring the booster home."
        )
        self.play(
            FadeOut(act5),
            FadeOut(divider),
            ReplacementTransform(narration, final_narration),
            *model.focus_anims(None),
            run_time=0.9
        )
        self.play(
            *model.center_anims(),
            *model.focus_anims({
                "first_stage_airframe": BLUE_3B1B,
                "second_stage_airframe": TEAL_3B1B,
                "payload_fairing": PURPLE_3B1B,
                "landing_legs": WHITE_3B1B
            }),
            run_time=1.5
        )
        final_eq = equation(
            r"\Delta v=v_e\ln\left(\frac{m_0}{m_f}\right):\ \mathrm{stage\ for\ speed,\ reserve\ for\ return}",
            (0.0, 2.82, 0.0),
            WHITE_3B1B,
            0.49,
            8.8
        )
        resolve = serif_text(
            "Nine engines begin the journey. Precision guidance finishes it—twice.",
            color=MUTED_3B1B,
            height=0.29,
            italic=True,
            max_width=9.8
        )
        resolve.move_to(np.array([0.0, -2.73, 0.0]))
        fix(resolve)
        self.play(
            Write(final_eq),
            FadeIn(resolve),
            run_time=1.4
        )
        self.move_camera(
            theta=32 * DEGREES,
            phi=72 * DEGREES,
            run_time=3.5
        )
        self.play(
            Circumscribe(
                final_eq,
                color=BLUE_DIM,
                stroke_width=1.2
            ),
            run_time=0.8
        )
        self.wait(1.0)
