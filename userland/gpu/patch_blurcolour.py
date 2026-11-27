"""lavender: blur and colour-matrix shaders as the first lavender project fixed them (eagl.c).

Seen 2026-11-27 (runs f600, h1139): white dock and a white/yellow search pill on the home screen,
coloured slivers in Settings - the blur materials. From the first project (commits ea74d71, e157d39,
877dd11), no boot-arg (they only make the picture right):
- colour-matrix functions (vibrant / group over: "vcm"; masking: "cm4") keep colour within opacity,
  premultiplied, as Apple's sgl_vcm/sgl_cm4: the bias lit transparent pixels and over-bright ones
  blended in as mint/cyan/white blocks behind blurs; nothing is drawn where nothing was;
- ds8 (the eight-times downsample at the start of every backdrop blur) without the vertex colour, as
  Apple's downsample_8_frag: CA leaves the colour array off for ds8 and it read whatever the array
  held last, (0,0,0,1) made opaque blocks in the blur cache (dark/flickering pill and dock);
- ds8 samples read level 0 (textureLod): the implicit LOD of a minifying sample may read stale
  mipmaps (dark/half pills, bitten plates).

usage: python patch_blurcolour.py EAGL_C   (run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new, count=1):
    global s
    assert s.count(old) == count, (old[:70], s.count(old))
    s = s.replace(old, new)


# vibrant_fragment and group_over_fragment carry the same body
sub('''    "  s = s.r * colours[0] + s.g * colours[1] + s.b * colours[2] + s.a * colours[3] + colours[4];\\n"
    "  s.a = clamp(s.a, 0., 1.);\\n"
    "  s.rgb = clamp(s.rgb * s.a, 0., 1.);\\n"
    "  result = mix(behind, s, layer.a);\\n"''', '''    "  s = clamp(s.r * colours[0] + s.g * colours[1] + s.b * colours[2] + s.a * colours[3] + colours[4], 0., 1.);\\n"
    "  s.rgb *= s.a;\\n"
    /* lavender (patch_blurcolour.py, as sgl_vcm): premultiplied, never more colour than opacity; nothing where nothing was */
    "  result = mix(behind, behind.a > 0. ? s : vec4(0.), layer.a);\\n"''', 2)
sub('''    "  result = clamp(s.r * colours[0] + s.g * colours[1] + s.b * colours[2] + s.a * colours[3] + colours[4], 0., 1.);\\n"''',
    '''    "  mediump vec4 u = clamp(s.r * colours[0] + s.g * colours[1] + s.b * colours[2] + s.a * colours[3] + colours[4], 0., 1.);\\n"
    /* lavender (patch_blurcolour.py, as sgl_cm4): premultiplied output, colour never above opacity */
    "  result = vec4(min(u.rgb, u.a), u.a);\\n"''')
sub('''    "    sum += texture(texture0, middle + places[i]) + texture(texture0, middle - places[i]);\\n"
    "    sum += texture(texture0, middle + places[i] * vec2(1., -1.)) + texture(texture0, middle + places[i] * vec2(-1., 1.));\\n"
    "  }\\n"
    "  result = color * sum * .0625;\\n"''', '''    "    sum += textureLod(texture0, middle + places[i], 0.) + textureLod(texture0, middle - places[i], 0.);\\n"
    "    sum += textureLod(texture0, middle + places[i] * vec2(1., -1.), 0.) + textureLod(texture0, middle + places[i] * vec2(-1., 1.), 0.);\\n"
    "  }\\n"
    /* lavender (patch_blurcolour.py): level 0 only, and no vertex colour, as Apple's downsample_8_frag */
    "  result = sum * .0625;\\n"''')
open(path, 'w', newline='\n').write(s)
print('ok')
