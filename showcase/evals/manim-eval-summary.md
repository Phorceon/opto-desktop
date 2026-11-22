# Manim eval manim-20261122-034014 — kimi-driven 3B1B Manim episodes

backend `direct`, model `moonshotai-kimi-k3.1-pro-trial`, quality `m`; pass **17%**, mean score **0.79**, scripts that ran first try: **1/6 (17%)**

| id | score | duration s | attempts | wall s | failed checks |
|---|---|---|---|---|---|
| apache_helicopter | 0.86 | 67.10 | 3 | 496.6 | non_blank_frames: 5/8 non-blank; stats=[{'mean': 1.76, 'std': 8.23}, {'mean': 5.79, 'std': 21.76}, {'mean': 4.2, 'std': 16.26}, {'mean': 3.02, 'std': 12.3}, {'mean': 2.5, 'std': 10.96}, {'mean': 6.73, 'std': 21.77}, {'mean': 5.59, 'std': 19.8}, {'mean': 9.11, 'std': 25.44}] |
| f22_raptor | 0.71 | 51.53 | 3 | 415.3 | uses_write_create: Write=False, Create=True<br>non_blank_frames: 5/8 non-blank; stats=[{'mean': 0.72, 'std': 4.58}, {'mean': 6.86, 'std': 23.29}, {'mean': 3.85, 'std': 17.35}, {'mean': 3.0, 'std': 12.64}, {'mean': 2.13, 'std': 11.15}, {'mean': 5.43, 'std': 18.21}, {'mean': 4.84, 'std': 18.01}, {'mean': 10.03, 'std': 28.76}] |
| falcon9_rocket | 1.00 | 65.53 | 2 | 403.6 | — |
| human_eye | 0.86 | 79.70 | 3 | 284.7 | runs: 3 attempt(s); mp4=10265.2 KB; last error: '_scene.py", line 513, in construct\n    self.play(\nTypeError: Unexpected argument <opto.manim_bridge.ForgeModel object at 0x7fa717799c70> passed to Scene.play().' |
| mechanical_watch | 0.43 | 81.27 | 2 | 215.1 | runs: 2 attempt(s); mp4=11724.2 KB; last error: 'Traceback (most recent call last):\nRuntimeError: video_scene.py defines no ThreeDScene subclass. Define OptoEpisode(ThreeDScene).'<br>uses_3d_model: load_forge_model=False, play_cutaway/focus_anims=False<br>uses_manim_math: math_tex=False; 0 primitives: []<br>uses_write_create: Write=False, Create=False |
| v8_engine | 0.86 | 69.83 | 1 | 186.6 | uses_write_create: Write=False, Create=True |
