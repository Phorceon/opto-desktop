#version 330

uniform sampler2D LightTexture;

in vec2 v_im_coords;
in float v_opacity;

out vec4 frag_color;

void main() {
    vec4 c = texture(LightTexture, v_im_coords);
    frag_color = vec4(c.rgb, c.a * v_opacity);
}
