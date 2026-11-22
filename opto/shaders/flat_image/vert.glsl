#version 330

in vec3 point;
in vec2 im_coords;
in float opacity;

out vec2 v_im_coords;
out float v_opacity;

const vec2 DEFAULT_FRAME_SHAPE = vec2(8.0 * 16.0 / 9.0, 8.0);

void main() {
    v_im_coords = im_coords;
    v_opacity = opacity;
    vec2 ndc = point.xy * 2.0 / DEFAULT_FRAME_SHAPE;
    gl_Position = vec4(ndc, -0.99, 1.0);
}
