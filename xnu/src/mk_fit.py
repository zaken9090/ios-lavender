"""lavender: show the whole 1125x2436 iPhone X canvas on the 1080x2340 panel (scaled by 0.96 in both
directions) instead of its cropped centre; touch mapped the same way. Boot-arg sweetfb_fit=0 restores
the crop. Also: touch report diagnostics in sweet_touch.c.

usage: python mk_fit.py XNU_TREE
"""
import sys

tree = sys.argv[1]


def edit(rel, pairs):
    p = f'{tree}/{rel}'
    s = open(p, newline='').read()
    for old, new in pairs:
        assert s.count(old) == 1, (rel, old[:70], s.count(old))
        s = s.replace(old, new)
    open(p, 'w', newline='\n').write(s)


FIT_COPY = r'''
/*
 * lavender: the presented canvas (1125x2436, iPhone X) is larger than the panel (1080x2340) by
 * the same factor in both directions (0.960 / 0.961): fit it instead of showing its cropped centre.
 * Nearest pixel: panel column px shows canvas column px * lw / pw (one table), row py likewise.
 * Boot-arg sweetfb_fit=0: crop as before.
 */
static int sweet_fb_fit = -1;

static bool
sweet_fb_fit_on(void)
{
	if (sweet_fb_fit < 0) {
		sweet_fb_fit = 1;
		PE_parse_boot_argn("sweetfb_fit", &sweet_fb_fit, sizeof(sweet_fb_fit));
	}
	return sweet_fb_fit != 0;
}

/* One layer: logical rect (dx, dy, w, h) from source (sx, sy) into the panel buffer. */
static void
sweet_fit_copy(uint8_t *dst, uint32_t dstRowBytes, uint32_t pw, uint32_t ph, uint32_t lw, uint32_t lh,
    const uint8_t *src, uint32_t srcRowBytes, uint64_t srcLen, uint32_t srcW, uint32_t srcH,
    int32_t sx, int32_t sy, int32_t dx, int32_t dy, int32_t w, int32_t h)
{
	static uint16_t col[2048];
	static uint32_t colFor;
	if (pw > 2048 || lw == 0 || pw == 0 || ph == 0) {
		return;
	}
	if (colFor != (pw << 16 | lw)) {
		for (uint32_t px = 0; px < pw; px++) {
			col[px] = (uint16_t)((uint64_t)px * lw / pw);
		}
		colFor = pw << 16 | lw;
	}
	if (sx < 0 || sy < 0) {
		sx = sy = 0;
	}
	if (dx < 0) {
		sx -= dx;
		w += dx;
		dx = 0;
	}
	if (dy < 0) {
		sy -= dy;
		h += dy;
		dy = 0;
	}
	if (w > (int32_t)lw - dx) {
		w = (int32_t)lw - dx;
	}
	if (h > (int32_t)lh - dy) {
		h = (int32_t)lh - dy;
	}
	if (w > (int32_t)srcW - sx) {
		w = (int32_t)srcW - sx;
	}
	if (h > (int32_t)srcH - sy) {
		h = (int32_t)srcH - sy;
	}
	if (w <= 0 || h <= 0 ||
	    (uint64_t)(sy + h - 1) * srcRowBytes + (uint64_t)(sx + w) * 4 > srcLen) {
		return;
	}
	/* First panel row/column whose canvas coordinate is >= the rect start, and past its end. */
	uint32_t px0 = (uint32_t)(((uint64_t)dx * pw + lw - 1) / lw);
	uint32_t px1 = (uint32_t)(((uint64_t)(dx + w) * pw + lw - 1) / lw);
	uint32_t py0 = (uint32_t)(((uint64_t)dy * ph + lh - 1) / lh);
	uint32_t py1 = (uint32_t)(((uint64_t)(dy + h) * ph + lh - 1) / lh);
	px1 = px1 > pw ? pw : px1;
	py1 = py1 > ph ? ph : py1;
	for (uint32_t py = py0; py < py1; py++) {
		uint32_t ly = (uint32_t)((uint64_t)py * lh / ph);
		const uint32_t *srow = (const uint32_t *)(src + (uint64_t)(sy + (int32_t)ly - dy) * srcRowBytes);
		uint32_t *drow = (uint32_t *)(dst + (uint64_t)py * dstRowBytes);
		for (uint32_t px = px0; px < px1; px++) {
			drow[px] = srow[sx + (int32_t)col[px] - dx];
		}
	}
}
'''

edit('iokit/Kernel/arm/SweetFramebuffer.cpp', [
    ('''extern "C" vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
''', '''extern "C" vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
''' + FIT_COPY),
    ('''		/* Logical (presented) display coordinates -> panel coordinates. */
		dx -= fOffX;
		dy -= fOffY;''', '''		if (sweet_fb_fit_on() && src != 0 && bpe == 4 && s->elementWidth == 1 && s->elementHeight == 1 &&
		    s->memory != NULL && s->offset < s->memory->getLength()) {
			sweet_fit_copy(dst, fRowBytes, fWidth, fHeight, fLogicalW, fLogicalH,
			    (const uint8_t *)(src + s->offset), s->bytesPerRow, s->memory->getLength() - s->offset,
			    s->width, s->height, sx, sy, dx, dy, w, h);
			s->release();
			continue;
		}
		/* Logical (presented) display coordinates -> panel coordinates. */
		dx -= fOffX;
		dy -= fOffY;'''),
])

edit('iokit/Kernel/arm/hid/SweetHID.cpp', [
    ('''	/* Panel pixels -> the presented 1125x2436 display (SweetFramebuffer.cpp). */
	IOFixed nx = (IOFixed)(((int64_t)(x + fOffX) << 16) / fLogicalW);
	IOFixed ny = (IOFixed)(((int64_t)(y + fOffY) << 16) / fLogicalH);''',
     '''	/* Panel pixels -> the presented 1125x2436 display (SweetFramebuffer.cpp). */
	static int fit = -1;
	if (fit < 0) {
		fit = 1;        /* lavender: the canvas is scaled to the whole panel (sweetfb_fit) */
		PE_parse_boot_argn("sweetfb_fit", &fit, sizeof(fit));
	}
	IOFixed nx = fit ? (IOFixed)(((int64_t)x << 16) / 1080) : (IOFixed)(((int64_t)(x + fOffX) << 16) / fLogicalW);
	IOFixed ny = fit ? (IOFixed)(((int64_t)y << 16) / 2340) : (IOFixed)(((int64_t)(y + fOffY) << 16) / fLogicalH);'''),
])

edit('bsd/dev/sweet_touch.c', [
    ('''	uint64_t reports, errors;
} lt;''', '''	uint64_t reports, errors;
	int diag;                       /* boot-arg sweettouchdiag: log the first N reports, then every 200th */
} lt;'''),
    ('''			if (i2c_read(NVT_ADDR, 0x00, r, NVT_REPORT_LEN) == 0) {
				lt.reports++;''', '''			if (i2c_read(NVT_ADDR, 0x00, r, NVT_REPORT_LEN) == 0) {
				lt.reports++;
				if ((int64_t)lt.reports <= lt.diag || (lt.diag && lt.reports % 200 == 0)) {
					printf("SWEET TOUCH: report %llu: %02x %02x %02x %02x %02x %02x | %02x %02x %02x %02x %02x %02x\\n",
					    lt.reports, r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11]);
				}'''),
    ('''	PE_parse_boot_argn("sweettouch", &enabled, sizeof(enabled));''',
     '''	PE_parse_boot_argn("sweettouch", &enabled, sizeof(enabled));
	lt.diag = 40;
	PE_parse_boot_argn("sweettouchdiag", &lt.diag, sizeof(lt.diag));'''),
])
print('ok')
