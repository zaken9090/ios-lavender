"""lavender: VIG0's QSEED3 scales a direct frame (1125x2436) to the panel (1080x2340) (patch 1021).

With the MDP scanning GPU pool frames itself (patch 1020) the picture was cut to a panel-sized
window (the iPhone X's 1125x2436 shown 1:1, edges off), while the copy path fits the whole
picture onto the panel (sweet_fit_copy). Now a direct frame of the presented size is fetched
whole and VIG0's QSEED3 scaler (VIG0 + 0xa00, as mdss_mdp_qseed3_setup in Xiaomi's lavender
kernel: bilinear, no LUT) makes the panel's size of it: the same picture as the copy path, and
touches keep their mapping. Frames shown any other way (copy path, console, boot buffer) turn
the scaler off again (scanFrom()). Boot-arg sweetfb_qseed=0: no scaler (cut window as 1020).
Idea from the user's first lavender project (its patch 1028, there for 750x1624 upscaling).

usage: python mk_qseed.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetFramebuffer.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	void          scanFrom(uint64_t pa, uint32_t stride);
''', '''	void          scanFrom(uint64_t pa, uint32_t stride);
	bool          fScaleOn;       /* lavender: VIG0's QSEED3 scales the presented size to the panel now */
	bool          fScaleWant;     /* ... for the next scanFrom() (directPresent), else off (xnu/src/mk_qseed.py) */
	void          scaleSet(bool on);
''')

# the scaler, set with the next flush
sub('''void
AppleCLCD::scanFrom(uint64_t pa, uint32_t stride)
{
	if (fVig0 == NULL || fCtl0 == NULL) {
		return;         /* lavender: no MDP access */
	}
''', '''/*
 * lavender: VIG0 fetches the whole presented picture (fLogicalW x fLogicalH) and its QSEED3 scaler
 * (VIG0 + 0xa00: bilinear, no LUT) makes the panel's size of it; off: fetch a panel-sized window
 * 1:1 as before. Latched with the next CTL flush (scanFrom). xnu/src/mk_qseed.py
 */
void
AppleCLCD::scaleSet(bool on)
{
	if (fVig0 == NULL || on == fScaleOn) {
		return;
	}
	volatile uint32_t *sc = fVig0 + 0xa00 / 4;
	uint32_t sw = on ? fLogicalW : fWidth, sh = on ? fLogicalH : fHeight;
	fVig0[0x00 / 4] = (sh << 16) | sw;              /* SSPP_SRC_SIZE */
	fVig0[0x04 / 4] = (sh << 16) | sw;              /* SSPP_SRC_IMG_SIZE */
	fVig0[0x08 / 4] = 0;                            /* SSPP_SRC_XY */
	for (uint32_t off = 0; off <= 32; off += 16) {  /* pixel extension, planes 0, 1/2, 3: none, all rows fetched */
		fVig0[(0x100 + off) / 4] = 0;
		fVig0[(0x104 + off) / 4] = 0;
		fVig0[(0x108 + off) / 4] = (sh << 16) | sw;
	}
	if (on) {
		/* phase steps in 1.21 fixed point: source pixels per panel pixel (> 1: down) */
		uint32_t stepx = (uint32_t)(((uint64_t)sw << 21) / fWidth), stepy = (uint32_t)(((uint64_t)sh << 21) / fHeight);
		sc[0x0c / 4] = 0;                       /* PHASE_INIT */
		sc[0x10 / 4] = stepx;                   /* PHASE_STEP_Y_H */
		sc[0x14 / 4] = stepy;                   /* PHASE_STEP_Y_V */
		sc[0x18 / 4] = stepx;                   /* PHASE_STEP_UV_H */
		sc[0x1c / 4] = stepy;                   /* PHASE_STEP_UV_V */
		sc[0x20 / 4] = 0x03040304;              /* PRELOAD */
		sc[0x40 / 4] = (sh << 16) | sw;         /* SRC_SIZE_Y_RGB_A */
		sc[0x44 / 4] = (sh << 16) | sw;         /* SRC_SIZE_UV */
		sc[0x48 / 4] = (fHeight << 16) | fWidth;        /* DST_SIZE */
		sc[0x04 / 4] = 1u | (1u << 14) | (3u << 16) | (3u << 24) | (1u << 31);  /* OP_MODE: on, bilinear */
	} else {
		sc[0x04 / 4] = 1u << 14;                /* OP_MODE: off */
	}
	__asm__ volatile("dsb sy" ::: "memory");
	if (on) {
		static bool told;
		if (!told) {
			told = true;
			IOLog("SWEET FB: VIG0 QSEED3 (version %#x) scales %ux%u to %ux%u\\n", sc[0], sw, sh, fWidth, fHeight);
		}
	}
	fScaleOn = on;
}

void
AppleCLCD::scanFrom(uint64_t pa, uint32_t stride)
{
	if (fVig0 == NULL || fCtl0 == NULL) {
		return;         /* lavender: no MDP access */
	}
	scaleSet(fScaleWant);                   /* lavender: only a direct frame of the presented size is scaled */
	fScaleWant = false;
''')

# the direct path: the whole presented picture, scaled
sub('''		uint32_t ox = (s->width - fWidth) / 2, oy = (s->height - fHeight) / 2;
		if (s->width == fLogicalW && s->height == fLogicalH) {
			ox = (uint32_t)fOffX;
			oy = (uint32_t)fOffY;
		}
		uint64_t pa = s->scanoutPhys + s->offset + (uint64_t)oy * s->bytesPerRow + (uint64_t)ox * 4;
		if ((pa & 0xf) == 0 && pa + (uint64_t)fHeight * s->bytesPerRow < (1ull << 32)) {''',
    '''		uint32_t ox = (s->width - fWidth) / 2, oy = (s->height - fHeight) / 2;
		if (s->width == fLogicalW && s->height == fLogicalH) {
			ox = (uint32_t)fOffX;
			oy = (uint32_t)fOffY;
		}
		/* lavender: a GPU pool frame of the presented size is fetched whole and scaled (mk_qseed.py) */
		static int qseed = -1;
		if (qseed < 0) {
			qseed = 1;
			PE_parse_boot_argn("sweetfb_qseed", &qseed, sizeof(qseed));
		}
		bool scaled = qseed != 0 && sweet_fb_fit_on() && s->gpuPool && s->width == fLogicalW && s->height == fLogicalH &&
		    (fLogicalW != fWidth || fLogicalH != fHeight);
		if (scaled) {
			ox = oy = 0;
		}
		uint64_t pa = s->scanoutPhys + s->offset + (uint64_t)oy * s->bytesPerRow + (uint64_t)ox * 4;
		if ((pa & 0xf) == 0 && pa + (uint64_t)(scaled ? fLogicalH : fHeight) * s->bytesPerRow < (1ull << 32)) {''')
sub('''					/* GPU pool memory (write-combined): the MDP scans the surface itself, no copy */
					scanFrom(pa, s->bytesPerRow);''', '''					/* GPU pool memory (write-combined): the MDP scans the surface itself, no copy */
					fScaleWant = scaled;
					scanFrom(pa, s->bytesPerRow);''')
open(path, 'w', newline='\n').write(s)
print('ok')
