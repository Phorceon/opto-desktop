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
            "How does the human eye focus light and see?",
            height=0.52, max_width=11.8
        ).move_to([0, 0.55, 0])
        underline = Line(
            [-3.4, -0.05, 0], [3.4, -0.05, 0],
            color=BLUE_3B1B, stroke_width=2
        )
        hook = serif_text(
            "How can a curved window and a flexible lens write an image onto living cells?",
            color=MUTED_3B1B, height=0.29, italic=True, max_width=10.8
        ).move_to([0, -0.65, 0])
        fix(title, underline, hook)
        self.play(FadeIn(title), run_time=0.8)
        self.play(Create(underline), FadeIn(hook), run_time=1.0)
        self.wait(0.7)
        self.play(FadeOut(title), FadeOut(underline), FadeOut(hook), run_time=0.6)

        model = load_forge_model(self)
        model.setup_camera(ambient_rate=0.07)
        model.play_blueprint_intro()

        divider = Line(
            [0.05, -3.0, 0], [0.05, 3.25, 0],
            color=BLUE_DIM, stroke_width=1.2
        )
        fix(divider)
        self.play(*model.move_left_anims(), Create(divider), run_time=1.2)

        def make_caption(text):
            mob = serif_text(
                text, color=WHITE_3B1B, height=0.27, max_width=12.6
            ).move_to([0, -3.35, 0])
            fix(mob)
            return mob

        def replace_caption(old, text):
            new = make_caption(text)
            self.play(FadeOut(old), FadeIn(new), run_time=0.55)
            return new

        caption = make_caption(
            "The sclera protects an optical system whose first refracting surface is the cornea."
        )
        self.play(FadeIn(caption), run_time=0.5)

        # Act 1: the real cutaway and a reduced optical eye.
        self.play(*model.focus_anims({
            "sclera": BLUE_3B1B,
            "cornea": GOLD_3B1B,
            "crystalline_lens": TEAL_3B1B,
            "retina": MAROON_3B1B
        }, dim_opacity=0.18), run_time=1.0)

        cornea_callout = model.make_callout(
            "cornea", "Cornea: the main refracting surface",
            GOLD_3B1B, pos=[-3.8, 2.6, 0]
        )
        retina_callout = model.make_callout(
            "retina", "Retina: the image plane",
            MAROON_3B1B, pos=[-3.8, -2.0, 0]
        )
        fix(cornea_callout, retina_callout)
        self.play(FadeIn(cornea_callout), FadeIn(retina_callout), run_time=0.7)

        model.play_cutaway(focus={
            "sclera": BLUE_3B1B,
            "aqueous_humor": BLUE_DIM,
            "vitreous_body": BLUE_DIM,
            "crystalline_lens": TEAL_3B1B,
            "retina": MAROON_3B1B
        })

        optical_title = serif_text(
            "A reduced optical eye", color=BLUE_3B1B,
            height=0.29, italic=True
        ).move_to([3.55, 3.0, 0])
        snell = math_tex(
            r"n_1\sin\theta_1=n_2\sin\theta_2",
            color=WHITE_3B1B, height=0.58
        ).move_to([3.55, 2.48, 0])
        axis = open_curve(
            [[0.65, 0, 0], [6.25, 0, 0]],
            color=MUTED_3B1B, stroke_width=1.2, smooth=False
        )
        cornea_pts = [
            [2.23 + 0.20 * (1 - (y / 0.95) ** 2), y, 0]
            for y in np.linspace(-0.95, 0.95, 45)
        ]
        cornea_curve = open_curve(
            cornea_pts, color=GOLD_3B1B, stroke_width=4, smooth=True
        )
        retina_pts = [
            [5.45 + 0.45 * np.cos(t), 0.95 * np.sin(t), 0]
            for t in np.linspace(-np.pi / 2, np.pi / 2, 45)
        ]
        retina_curve = open_curve(
            retina_pts, color=MAROON_3B1B, stroke_width=4, smooth=True
        )

        bend = ValueTracker(0.18)

        def distant_optics():
            a = bend.get_value()
            width = 0.13 + 0.10 * a
            theta = np.linspace(0, 2 * np.pi, 57)
            lens_pts = [
                [4.05 + width * np.cos(t), 0.62 * np.sin(t), 0]
                for t in theta
            ]
            lens = open_curve(
                lens_pts, color=TEAL_3B1B, stroke_width=3, smooth=False
            )
            front_x = 4.05 - width
            lens_y = 0.43 + 0.035 * a
            rays = []
            for sign in [-1, 1]:
                ray = open_curve([
                    [0.72, sign * 0.84, 0],
                    [2.37, sign * 0.84, 0],
                    [front_x, sign * lens_y, 0],
                    [5.90, 0, 0]
                ], color=YELLOW_3B1B, stroke_width=2.5, smooth=False)
                rays.append(ray)
            focus_dot = Dot([5.90, 0, 0], radius=0.065, color=GOLD_3B1B)
            fix(lens, *rays, focus_dot)
            group = VGroup(lens, *rays, focus_dot)
            fix(group)
            return group

        optics = always_redraw(distant_optics)
        optical_labels = Group(
            serif_text(
                "Cornea", color=GOLD_3B1B, height=0.22
            ).move_to([2.18, 1.30, 0]),
            serif_text(
                "Crystalline lens", color=TEAL_3B1B, height=0.22
            ).move_to([4.05, -1.18, 0]),
            serif_text(
                "Retina", color=MAROON_3B1B, height=0.22
            ).move_to([5.68, 1.30, 0])
        )
        powers = math_tex(
            r"P_{\mathrm{cornea}}\approx43\,\mathrm{D},\qquad P_{\mathrm{lens}}\approx20\,\mathrm{D}",
            color=MUTED_3B1B, height=0.38, max_width=5.5
        ).move_to([3.55, -1.92, 0])
        fix(
            optical_title, snell, axis, cornea_curve, retina_curve,
            optics, optical_labels, powers
        )
        self.play(FadeIn(optical_title), Write(snell), run_time=0.9)
        self.play(
            Create(axis), Create(cornea_curve), Create(retina_curve),
            FadeIn(optical_labels), run_time=1.0
        )
        self.add(optics)
        self.play(Write(powers), run_time=0.8)
        self.play(bend.animate.set_value(0.48), run_time=1.4)
        self.wait(0.4)

        # Act 2: aperture area controls collected luminous flux.
        caption = replace_caption(
            caption,
            "The iris changes the pupil diameter, so retinal illumination scales approximately with aperture area."
        )
        self.play(*model.focus_anims({
            "cornea": GOLD_3B1B,
            "iris_and_pupil": PURPLE_3B1B,
            "aqueous_humor": BLUE_DIM
        }, dim_opacity=0.18), run_time=0.9)
        pupil_callout = model.make_callout(
            "iris_and_pupil", "Iris and pupil: a variable aperture",
            PURPLE_3B1B, pos=[-3.8, 2.6, 0]
        )
        fix(pupil_callout)
        self.play(FadeOut(cornea_callout), FadeIn(pupil_callout), run_time=0.5)

        optical_board = Group(
            optical_title, snell, axis, cornea_curve,
            retina_curve, optical_labels, powers
        )
        fix(optical_board)
        self.remove(optics)
        self.play(FadeOut(optical_board), run_time=0.7)

        aperture_title = serif_text(
            "The pupil, viewed from in front", color=PURPLE_3B1B,
            height=0.29, italic=True
        ).move_to([3.55, 2.95, 0])
        aperture_eq = math_tex(
            r"A=\pi\left(\frac{D}{2}\right)^2,\qquad \Phi_{\mathrm{retina}}\propto D^2",
            color=WHITE_3B1B, height=0.57, max_width=5.5
        ).move_to([3.55, 2.30, 0])
        iris_outline = open_curve(
            [
                [3.55 + 0.95 * np.cos(t), 0.25 + 0.95 * np.sin(t), 0]
                for t in np.linspace(0, 2 * np.pi, 65)
            ],
            color=PURPLE_3B1B, stroke_width=3, smooth=False
        )
        iris_label = serif_text(
            "Iris", color=PURPLE_3B1B, height=0.23
        ).move_to([4.85, 0.25, 0])
        aperture_note = math_tex(
            r"\mathrm{dim\ light}:D\uparrow\ \Rightarrow\ \Phi\uparrow",
            color=GOLD_3B1B, height=0.43
        ).move_to([3.55, -1.55, 0])
        aperture = ValueTracker(0.26)

        def pupil_geometry():
            r = aperture.get_value()
            ring = open_curve(
                [
                    [3.55 + r * np.cos(t), 0.25 + r * np.sin(t), 0]
                    for t in np.linspace(0, 2 * np.pi, 65)
                ],
                color=GOLD_3B1B, stroke_width=3, smooth=False
            )
            diameter = Line(
                [3.55 - r, 0.25, 0], [3.55 + r, 0.25, 0],
                color=WHITE_3B1B, stroke_width=1.5
            )
            left_tick = Line(
                [3.55 - r, 0.17, 0], [3.55 - r, 0.33, 0],
                color=WHITE_3B1B, stroke_width=1.5
            )
            right_tick = Line(
                [3.55 + r, 0.17, 0], [3.55 + r, 0.33, 0],
                color=WHITE_3B1B, stroke_width=1.5
            )
            fix(ring, diameter, left_tick, right_tick)
            group = VGroup(ring, diameter, left_tick, right_tick)
            fix(group)
            return group

        pupil = always_redraw(pupil_geometry)
        fix(
            aperture_title, aperture_eq, iris_outline,
            iris_label, aperture_note, pupil
        )
        self.play(FadeIn(aperture_title), Write(aperture_eq), run_time=0.8)
        self.play(Create(iris_outline), FadeIn(iris_label), run_time=0.7)
        self.add(pupil)
        self.play(aperture.animate.set_value(0.72), run_time=1.7)
        self.play(Write(aperture_note), run_time=0.8)
        self.play(aperture.animate.set_value(0.32), run_time=1.5)
        self.wait(0.3)

        # Act 3: accommodation reshapes the crystalline lens.
        caption = replace_caption(
            caption,
            "For near vision, the ciliary body relaxes zonular tension and the lens becomes rounder and more powerful."
        )
        self.play(*model.focus_anims({
            "ciliary_body": MAROON_3B1B,
            "zonular_fibers": GOLD_3B1B,
            "crystalline_lens": TEAL_3B1B
        }, dim_opacity=0.18), run_time=0.9)
        lens_callout = model.make_callout(
            "crystalline_lens", "Accommodation reshapes the lens",
            TEAL_3B1B, pos=[-3.8, 2.6, 0]
        )
        zonule_callout = model.make_callout(
            "zonular_fibers", "Zonular fibers",
            GOLD_3B1B, pos=[-3.8, -2.0, 0]
        )
        fix(lens_callout, zonule_callout)
        self.play(
            FadeOut(pupil_callout), FadeOut(retina_callout),
            FadeIn(lens_callout), FadeIn(zonule_callout), run_time=0.6
        )

        aperture_board = Group(
            aperture_title, aperture_eq, iris_outline,
            iris_label, aperture_note
        )
        fix(aperture_board)
        self.remove(pupil)
        self.play(FadeOut(aperture_board), run_time=0.7)

        accommodate = ValueTracker(0.0)
        lensmaker = math_tex(
            r"P_{\mathrm{lens}}=(n_{\mathrm{rel}}-1)\left(\frac{1}{R_1}-\frac{1}{R_2}\right)",
            color=WHITE_3B1B, height=0.53, max_width=5.7
        ).move_to([3.55, 2.58, 0])
        imaging = math_tex(
            r"\frac{1}{f}=\frac{1}{s}+\frac{1}{s'}",
            color=TEAL_3B1B, height=0.52
        ).move_to([3.55, 1.83, 0])
        near_rule = math_tex(
            r"\mathrm{near\ object}:\quad s\downarrow\ \Rightarrow\ P\uparrow",
            color=GOLD_3B1B, height=0.43
        ).move_to([3.55, -1.92, 0])
        accommodation_axis = open_curve(
            [[0.65, 0, 0], [6.25, 0, 0]],
            color=MUTED_3B1B, stroke_width=1.2, smooth=False
        )
        accommodation_retina = open_curve(
            retina_pts, color=MAROON_3B1B, stroke_width=4, smooth=True
        )
        accommodation_cornea = open_curve(
            cornea_pts, color=GOLD_3B1B, stroke_width=3, smooth=True
        )
        ciliary_top = Dot(
            [4.05, 1.02, 0], radius=0.085, color=MAROON_3B1B
        )
        ciliary_bottom = Dot(
            [4.05, -1.02, 0], radius=0.085, color=MAROON_3B1B
        )
        fixed_focus = Dot(
            [5.90, 0, 0], radius=0.065, color=GOLD_3B1B
        )
        accommodation_labels = Group(
            serif_text(
                "Ciliary body", color=MAROON_3B1B, height=0.21
            ).move_to([4.02, 1.35, 0]),
            serif_text(
                "Foveal focus", color=GOLD_3B1B, height=0.21
            ).move_to([5.72, -0.48, 0])
        )
        fix(
            accommodation_axis, accommodation_retina,
            accommodation_cornea, ciliary_top, ciliary_bottom,
            fixed_focus, accommodation_labels, lensmaker, imaging, near_rule
        )

        def accommodation_geometry():
            a = accommodate.get_value()
            width = 0.12 + 0.17 * a
            lens = open_curve(
                [
                    [4.05 + width * np.cos(t), 0.62 * np.sin(t), 0]
                    for t in np.linspace(0, 2 * np.pi, 57)
                ],
                color=TEAL_3B1B, stroke_width=3.5, smooth=False
            )
            source_x = 0.72 + 0.64 * a
            source = Dot(
                [source_x, 0, 0], radius=0.07, color=WHITE_3B1B
            )
            front_x = 4.05 - width
            lens_y = 0.43 + 0.055 * a
            rays = []
            for sign in [-1, 1]:
                ray = open_curve([
                    [source_x, 0, 0],
                    [2.36, sign * (0.74 + 0.08 * a), 0],
                    [front_x, sign * lens_y, 0],
                    [5.90, 0, 0]
                ], color=YELLOW_3B1B, stroke_width=2.5, smooth=False)
                rays.append(ray)
            zon_top = open_curve([
                [4.05, 1.02, 0],
                [3.92 - 0.10 * a, 0.76, 0],
                [front_x, 0.52, 0]
            ], color=GOLD_3B1B, stroke_width=1.8, smooth=False)
            zon_bottom = open_curve([
                [4.05, -1.02, 0],
                [3.92 - 0.10 * a, -0.76, 0],
                [front_x, -0.52, 0]
            ], color=GOLD_3B1B, stroke_width=1.8, smooth=False)
            fix(lens, source, *rays, zon_top, zon_bottom)
            group = VGroup(lens, source, *rays, zon_top, zon_bottom)
            fix(group)
            return group

        accommodation_scene = always_redraw(accommodation_geometry)
        fix(accommodation_scene)
        self.play(Write(lensmaker), Write(imaging), run_time=0.8)
        self.play(
            Create(accommodation_axis), Create(accommodation_retina),
            Create(accommodation_cornea), FadeIn(accommodation_labels),
            run_time=0.8
        )
        self.add(accommodation_scene)
        self.play(accommodate.animate.set_value(1.0), run_time=3.0)
        self.play(Write(near_rule), run_time=0.8)
        self.play(accommodate.animate.set_value(0.12), run_time=1.4)
        self.play(accommodate.animate.set_value(0.88), run_time=1.5)

        # Act 4: authentic light flow followed by retinal transduction.
        caption = replace_caption(
            caption,
            "Focused rays land near the fovea; photoreceptors convert absorbed light into signals for the optic nerve."
        )
        self.play(*model.focus_anims({
            "focused_light_rays": GOLD_3B1B,
            "cornea": GOLD_3B1B,
            "crystalline_lens": TEAL_3B1B,
            "fovea": MAROON_3B1B,
            "retina": MAROON_3B1B
        }, dim_opacity=0.18), run_time=0.9)
        fovea_callout = model.make_callout(
            "fovea", "Fovea: dense cone sampling",
            MAROON_3B1B, pos=[-3.8, 2.6, 0]
        )
        fix(fovea_callout)
        self.play(
            FadeOut(lens_callout), FadeOut(zonule_callout),
            FadeIn(fovea_callout), run_time=0.5
        )
        self.play(Indicate(fixed_focus, color=GOLD_3B1B), run_time=0.8)
        model.play_flow(duration=3.0)
        model.clear_flow()

        accommodation_board = Group(
            lensmaker, imaging, near_rule, accommodation_axis,
            accommodation_retina, accommodation_cornea,
            ciliary_top, ciliary_bottom, fixed_focus,
            accommodation_labels
        )
        fix(accommodation_board)
        self.remove(accommodation_scene)
        self.play(FadeOut(accommodation_board), run_time=0.8)
        self.play(*model.focus_anims({
            "rods_and_cones": GOLD_3B1B,
            "fovea": MAROON_3B1B,
            "optic_disc": PURPLE_3B1B,
            "optic_nerve": PURPLE_3B1B
        }, dim_opacity=0.18), run_time=0.9)
        nerve_callout = model.make_callout(
            "optic_nerve", "Optic nerve: neural output",
            PURPLE_3B1B, pos=[-3.8, -2.0, 0]
        )
        fix(nerve_callout)
        self.play(FadeOut(fovea_callout), FadeIn(nerve_callout), run_time=0.5)

        response_eq = math_tex(
            r"R(I)=R_{\mathrm{max}}\frac{I}{I+I_{1/2}}",
            color=WHITE_3B1B, height=0.55
        ).move_to([3.55, 2.65, 0])
        response_title = serif_text(
            "Photoreceptor response saturates", color=GOLD_3B1B,
            height=0.27, italic=True
        ).move_to([3.55, 2.08, 0])
        ax = Axes(
            x_range=[0, 4, 1], y_range=[0, 1.1, 0.5],
            x_length=4.5, y_length=2.0,
            axis_config={"color": MUTED_3B1B, "stroke_width": 1.5},
            tips=False
        ).move_to([3.55, 0.35, 0])
        response_curve = ax.plot(
            lambda intensity_value: intensity_value / (intensity_value + 0.60),
            x_range=[0, 4], color=GOLD_3B1B, stroke_width=3
        )
        intensity_label = serif_text(
            "Absorbed light, I", color=MUTED_3B1B, height=0.20
        ).move_to([4.15, -0.94, 0])
        response_label = serif_text(
            "R", color=MUTED_3B1B, height=0.20
        ).move_to([1.02, 0.52, 0])
        intensity = ValueTracker(0.15)

        def response_marker():
            i = intensity.get_value()
            response = i / (i + 0.60)
            point = ax.coords_to_point(i, response)
            base = ax.coords_to_point(i, 0)
            dot = Dot(point, radius=0.065, color=YELLOW_3B1B)
            guide = Line(
                base, point, color=BLUE_DIM, stroke_width=1.2
            )
            fix(dot, guide)
            group = VGroup(dot, guide)
            fix(group)
            return group

        marker = always_redraw(response_marker)
        transduction = math_tex(
            r"h\nu\rightarrow\mathrm{rhodopsin}^{*}\rightarrow\Delta V<0\rightarrow\mathrm{neural\ signal}",
            color=PURPLE_3B1B, height=0.40, max_width=5.8
        ).move_to([3.55, -1.55, 0])
        receptors = []
        for x in [2.55, 3.25, 3.95]:
            cone = open_curve([
                [x - 0.11, -2.08, 0],
                [x + 0.11, -2.08, 0],
                [x + 0.07, -1.73, 0],
                [x - 0.07, -1.73, 0],
                [x - 0.11, -2.08, 0]
            ], color=GOLD_3B1B, stroke_width=2, smooth=False)
            receptors.append(cone)
        cone_group = VGroup(*receptors)
        rod = Line(
            [4.85, -2.08, 0], [4.85, -1.70, 0],
            color=BLUE_3B1B, stroke_width=5
        )
        receptor_label = serif_text(
            "Cones                         Rod", color=MUTED_3B1B,
            height=0.18
        ).move_to([3.60, -2.28, 0])
        signal_path = open_curve(
            [[4.90, -1.87, 0], [5.45, -1.87, 0], [6.15, -1.60, 0]],
            color=PURPLE_3B1B, stroke_width=2, smooth=False
        )
        signal_pulse = Dot(
            [4.90, -1.87, 0], radius=0.065, color=PURPLE_3B1B
        )
        retinal_board = Group(
            response_eq, response_title, ax, response_curve,
            intensity_label, response_label, transduction,
            cone_group, rod, receptor_label, signal_path, signal_pulse
        )
        fix(
            marker, cone_group, rod, signal_path,
            signal_pulse, retinal_board
        )
        self.play(
            Write(response_eq), FadeIn(response_title), Create(ax),
            run_time=1.0
        )
        self.play(
            Create(response_curve), FadeIn(intensity_label),
            FadeIn(response_label), run_time=0.9
        )
        self.add(marker)
        self.play(intensity.animate.set_value(3.55), run_time=2.3)
        self.play(intensity.animate.set_value(0.65), run_time=1.2)
        self.play(
            Write(transduction), FadeIn(cone_group), FadeIn(rod),
            FadeIn(receptor_label), Create(signal_path), run_time=1.0
        )
        self.add(signal_pulse)
        self.play(MoveAlongPath(signal_pulse, signal_path), run_time=1.4)
        self.wait(0.3)

        # Finale: restore the whole eye and resolve the optical-to-neural chain.
        self.play(*model.focus_anims(None), run_time=0.8)
        self.remove(marker)
        self.play(
            *model.center_anims(),
            FadeOut(retinal_board), FadeOut(nerve_callout),
            FadeOut(caption), FadeOut(divider), run_time=1.5
        )
        self.play(*model.focus_anims({
            "sclera": BLUE_3B1B,
            "cornea": GOLD_3B1B,
            "crystalline_lens": TEAL_3B1B,
            "retina": MAROON_3B1B,
            "optic_nerve": PURPLE_3B1B
        }, dim_opacity=0.24), run_time=0.8)

        final_formula = math_tex(
            r"\mathrm{light}\rightarrow\mathrm{focused\ retinal\ image}\rightarrow\mathrm{neural\ signal}",
            color=WHITE_3B1B, height=0.59, max_width=7.6
        ).move_to([0, 2.65, 0])
        final_optics = math_tex(
            r"n_1\sin\theta_1=n_2\sin\theta_2,\qquad \frac{1}{f}=\frac{1}{s}+\frac{1}{s'}",
            color=TEAL_3B1B, height=0.45, max_width=7.0
        ).move_to([0, -2.55, 0])
        final_caption = make_caption(
            "The cornea supplies most refraction, the lens fine-tunes focus, and retinal cells turn that image into sight."
        )
        fix(final_formula, final_optics, final_caption)
        self.play(
            Write(final_formula), Write(final_optics),
            FadeIn(final_caption), run_time=1.2
        )
        self.play(*model.focus_anims(None), run_time=0.8)
        self.begin_ambient_camera_rotation(rate=0.08)
        self.wait(4.0)
        self.stop_ambient_camera_rotation()
