/*
 * ios-lavender shim, stage E2 probe v2.
 * Started by ABL through `fastboot boot` in place of a Linux kernel (Silver cpu0, EL1, MMU off,
 * x0 = device tree). Prints what it measures on the framebuffer ABL left running, starts a Gold
 * core, turns on a 16K-granule MMU there and raises the Gold clock step by step.
 */
#include <stdarg.h>
#include "font.h"

typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long u64;

/* docs/HARDWARE.md */
#define FB_BASE     0x9d400000UL
#define FB_W        1080
#define FB_H        2340
#define SCALE       3
#define COLS        (FB_W / (8 * SCALE))
#define ROWS        (FB_H / (16 * SCALE))

#define PSCI_CPU_ON         0xc4000003UL
#define PSCI_SYSTEM_RESET   0x84000009UL
#define GOLD0_MPIDR         0x100UL

/* CPU clock controller (APCS). PLL: +0 mode, +4 L (rate = L * 19.2 MHz), +0x2c status, bit 16 = locked. */
#define PLL_SILVER      0x17916000UL
#define PLL_GOLD        0x17816000UL
#define GOLD_RCG_CMD    0x17811050UL
#define GOLD_RCG_CFG    0x17811054UL    /* bits 10:8 source: 3 = own PLL, 4 = GPLL0 */
#define OSM_CLK_CMD     0x179d112cUL    /* clock of the OSM block that paces the Gold clock */
#define OSM_CLK_CFG     0x179d1130UL

u64 smc_call(u64 fn, u64 a1, u64 a2, u64 a3);
void secondary_entry(void);

#define READ_SYSREG(name) ({ u64 v_; __asm__ volatile("mrs %0, " #name : "=r"(v_)); v_; })
#define WRITE_SYSREG(name, v) do { u64 v_ = (v); __asm__ volatile("msr " #name ", %0" :: "r"(v_)); } while (0)
#define ISB() __asm__ volatile("isb")

static u32 rd32(u64 a) { return *(volatile u32 *)a; }
static void wr32(u64 a, u32 v) { *(volatile u32 *)a = v; __asm__ volatile("dsb sy" ::: "memory"); }

void *memset(void *d, int c, u64 n) { u8 *p = d; while (n--) *p++ = (u8)c; return d; }
void *memcpy(void *d, const void *s, u64 n) { u8 *p = d; const u8 *q = s; while (n--) *p++ = *q++; return d; }

/* ---- framebuffer console (x8r8g8b8, stride = width) ---- */

#define WHITE 0xffffffff
#define GREEN 0xff40ff40
#define RED   0xffff4040
#define CYAN  0xff40ffff

static int cur_col, cur_row;
static u32 fg = WHITE, bg = 0xff000000;

static void fill(int x, int y, int w, int h, u32 colour)
{
    volatile u32 *fb = (volatile u32 *)FB_BASE;
    for (int j = y; j < y + h && j < FB_H; j++)
        for (int i = x; i < x + w && i < FB_W; i++)
            fb[j * FB_W + i] = colour;
}

static void draw_char(int col, int row, char c)
{
    const u8 *glyph = font8x16[(c < 32 || c > 126) ? 0 : c - 32];
    for (int y = 0; y < 16; y++)
        for (int x = 0; x < 8; x++)
            fill((col * 8 + x) * SCALE, (row * 16 + y) * SCALE, SCALE, SCALE,
                 (glyph[y] & (0x80 >> x)) ? fg : bg);
}

static void put_char(char c)
{
    if (c == '\n' || cur_col >= COLS) {
        for (; cur_col < COLS; cur_col++)
            draw_char(cur_col, cur_row, ' ');
        cur_col = 0;
        if (++cur_row >= ROWS)
            cur_row = 0;
        if (c == '\n')
            return;
    }
    draw_char(cur_col++, cur_row, c);
}

static void put_num(u64 v, int base, int width)
{
    char buf[20];
    int n = 0;
    do {
        int d = (int)(v % (u64)base);
        buf[n++] = (char)(d < 10 ? '0' + d : 'a' + d - 10);
        v /= (u64)base;
    } while (v);
    while (width-- > n)
        put_char('0');
    while (n)
        put_char(buf[--n]);
}

/* %s %c %x %d (every number argument must be 64-bit), optional zero-padding width: %08x */
static void kprintf(const char *f, ...)
{
    va_list ap;
    va_start(ap, f);
    for (; *f; f++) {
        if (*f != '%') { put_char(*f); continue; }
        int width = 0;
        for (f++; *f >= '0' && *f <= '9'; f++)
            width = width * 10 + (*f - '0');
        if (*f == 's') { const char *s = va_arg(ap, const char *); while (*s) put_char(*s++); }
        else if (*f == 'c') put_char((char)va_arg(ap, u64));
        else if (*f == 'x') put_num(va_arg(ap, u64), 16, width);
        else if (*f == 'd') put_num(va_arg(ap, u64), 10, width);
        else put_char(*f);
    }
    va_end(ap);
}

/* ---- time and speed ---- */

static u64 ticks(void) { return READ_SYSREG(cntvct_el0); }

static void delay_ms(u64 ms)
{
    u64 end = ticks() + READ_SYSREG(cntfrq_el0) / 1000 * ms;
    while (ticks() < end)
        ;
}

/* Core clock in MHz: PMU cycle counter against the 19.2 MHz system timer, over 20 ms. */
static u64 cpu_mhz(void)
{
    WRITE_SYSREG(pmcr_el0, READ_SYSREG(pmcr_el0) | 1 | (1 << 6));   /* enable, 64-bit cycle counter */
    WRITE_SYSREG(pmcntenset_el0, 1UL << 31);
    ISB();
    u64 f = READ_SYSREG(cntfrq_el0), t0 = ticks(), c0 = READ_SYSREG(pmccntr_el0);
    while (ticks() - t0 < f / 50)
        ;
    u64 c1 = READ_SYSREG(pmccntr_el0), t1 = ticks();
    return (c1 - c0) * (f / 1000) / (t1 - t0) / 1000;
}

/* Milliseconds to write 4 MB of RAM in the second bank. */
static u64 mem_fill_ms(void)
{
    volatile u64 *p = (volatile u64 *)0x110000000UL;
    u64 t0 = ticks();
    for (u64 i = 0; i < (4UL << 20) / 8; i++)
        p[i] = i;
    return (ticks() - t0) * 1000 / READ_SYSREG(cntfrq_el0);
}

/* Deterministic arithmetic + memory workload; a wrong result means the core is not stable. */
static u64 stress_buf[4096];
static u64 stress_sum(void)
{
    u64 h = 0x9e3779b97f4a7c15UL;
    memset(stress_buf, 0, sizeof stress_buf);
    for (u64 i = 0; i < 300000; i++) {
        h = (h ^ i) * 0x100000001b3UL;
        h = ((h << 13) | (h >> 51)) + stress_buf[i & 4095];
        stress_buf[(i * 7) & 4095] = h;
    }
    return h;
}

/* ---- flattened device tree (big endian, read bytewise: alignment is not guaranteed) ---- */

static u32 be32(const u8 *p) { return (u32)p[0] << 24 | (u32)p[1] << 16 | (u32)p[2] << 8 | p[3]; }
static u64 be64(const u8 *p) { return (u64)be32(p) << 32 | be32(p + 4); }
static int starts(const char *s, const char *prefix) { while (*prefix) if (*s++ != *prefix++) return 0; return 1; }
static int str_eq(const char *a, const char *b) { while (*a && *a == *b) a++, b++; return *a == *b; }

/* Prints the RAM banks ABL wrote into /memory. */
static void fdt_report(const u8 *fdt)
{
    if (be32(fdt) != 0xd00dfeed) {
        kprintf("FDT: bad magic %08x\n", (u64)be32(fdt));
        return;
    }
    const u8 *p = fdt + be32(fdt + 8);
    const char *strings = (const char *)fdt + be32(fdt + 12);
    int depth = 0, in_memory = 0;
    for (;;) {
        u32 tok = be32(p);
        p += 4;
        if (tok == 1) {
            const char *name = (const char *)p;
            u32 n = 0;
            while (p[n]) n++;
            p += (n + 4) & ~3u;
            if (++depth == 2)
                in_memory = starts(name, "memory");
        } else if (tok == 2) {
            if (--depth < 2)
                in_memory = 0;
            if (depth == 0)
                break;
        } else if (tok == 3) {
            u32 len = be32(p);
            const char *name = strings + be32(p + 4);
            const u8 *val = p + 8;
            p += 8 + ((len + 3) & ~3u);
            if (depth == 2 && in_memory && str_eq(name, "reg"))
                for (u32 o = 0; o + 16 <= len; o += 16)
                    kprintf("RAM %x + %x\n", be64(val + o), be64(val + o + 8));
        } else if (tok == 9) {
            break;
        }
    }
}

/* ---- reports ---- */

static void cpu_report(const char *who)
{
    u64 midr = READ_SYSREG(midr_el1), mmfr0 = READ_SYSREG(id_aa64mmfr0_el1);
    kprintf("%s EL%d MPIDR %x part %x MMFR0 %x\n", who, (READ_SYSREG(CurrentEL) >> 2) & 3,
            READ_SYSREG(mpidr_el1) & 0xffffff, (midr >> 4) & 0xfff, mmfr0);
    kprintf("%s 16K pages: %s   clock %d MHz\n", who, ((mmfr0 >> 20) & 0xf) ? "YES" : "NO", cpu_mhz());
}

static void pll_report(const char *who, u64 pll)
{
    u64 l = rd32(pll + 4) & 0xff;
    kprintf("%s PLL mode %x L %d (%d MHz) %s\n", who, (u64)rd32(pll), l, l * 192 / 10,
            (rd32(pll + 0x2c) & (1u << 16)) ? "locked" : "UNLOCKED");
}

static void countdown_and_reset(void)
{
    fg = WHITE;
    for (int left = 120; left > 0; left -= 5) {
        int row = cur_row;
        kprintf("reset in %d s  ", (u64)left);
        cur_col = 0;
        cur_row = row;
        delay_ms(5000);
    }
    smc_call(PSCI_SYSTEM_RESET, 0, 0, 0);
}

void exc_report(u64 vector, u64 esr, u64 elr, u64 far)
{
    fg = RED;
    kprintf("\nEXCEPTION vec %d MPIDR %x\nESR %x\nELR %x\nFAR %x\n", vector,
            READ_SYSREG(mpidr_el1) & 0xffffff, esr, elr, far);
}

/* ---- 16K-granule identity map ---- */

/*
 * 36-bit address space, 16K granule: translation starts at level 2, one table of 2048 entries,
 * each a 32 MB block. MMIO below 2 GB is device memory, the two RAM banks are cached, the block
 * holding the framebuffer is uncached so pixels reach the panel at once.
 */
static u64 l2_table[2048] __attribute__((aligned(16384)));

#define BLOCK       0x1UL
#define AF          (1UL << 10)
#define SH_INNER    (3UL << 8)
#define ATTR(n)     ((u64)(n) << 2)
#define XN          (3UL << 53)
#define BLOCK_SIZE  (32UL << 20)

static void mmu_16k_on(void)
{
    for (u64 i = 0; i < 2048; i++) {
        u64 addr = i * BLOCK_SIZE;
        if (addr < 0x80000000UL)
            l2_table[i] = addr | BLOCK | AF | ATTR(0) | XN;                 /* device */
        else if (addr == (FB_BASE & ~(BLOCK_SIZE - 1)))
            l2_table[i] = addr | BLOCK | AF | SH_INNER | ATTR(2) | XN;      /* framebuffer */
        else if (addr < 0x180000000UL)
            l2_table[i] = addr | BLOCK | AF | SH_INNER | ATTR(1);           /* RAM */
        else
            l2_table[i] = 0;
    }
    WRITE_SYSREG(mair_el1, 0x00UL | (0xffUL << 8) | (0x44UL << 16));         /* device, cached, uncached */
    WRITE_SYSREG(tcr_el1, 28UL | (1UL << 8) | (1UL << 10) | (3UL << 12) |   /* T0SZ, write-back caches, inner shareable */
                          (2UL << 14) | (1UL << 23) | (2UL << 32));         /* TG0 = 16K, no TTBR1, 40-bit PA */
    WRITE_SYSREG(ttbr0_el1, (u64)l2_table);
    ISB();
    __asm__ volatile("tlbi vmalle1\n dsb sy\n ic iallu\n dsb sy\n isb");
    WRITE_SYSREG(sctlr_el1, READ_SYSREG(sctlr_el1) | 1 | (1 << 2) | (1 << 12));   /* MMU, D-cache, I-cache */
    ISB();
}

/* ---- Gold clock ---- */

static void rcg_update(u64 cmd, u64 cfg, u32 value)
{
    wr32(cfg, value);
    wr32(cmd, 0x3);
    for (int n = 0; (rd32(cmd) & 1) && n < 100000; n++)
        ;
    ISB();
}

static void gold_source(u32 src)
{
    rcg_update(GOLD_RCG_CMD, GOLD_RCG_CFG, (rd32(GOLD_RCG_CFG) & ~0x71fu) | (src << 8) | 1u);
}

/* Park Gold on GPLL0, relock its PLL at L, switch back. Returns 0 when the PLL locked. */
static int gold_set_l(u32 l)
{
    gold_source(4);
    wr32(PLL_GOLD, 0);
    wr32(PLL_GOLD + 4, l);
    wr32(PLL_GOLD, 2);
    delay_ms(1);
    wr32(PLL_GOLD, 6);
    delay_ms(1);
    wr32(PLL_GOLD, 7);
    for (int n = 0; !(rd32(PLL_GOLD + 0x2c) & (1u << 16)) && n < 100000; n++)
        ;
    if (!(rd32(PLL_GOLD + 0x2c) & (1u << 16)))
        return -1;
    gold_source(3);
    return 0;
}

static void gold_clock_ladder(void)
{
    static const u8 steps[] = { 58, 80, 96, 115 };
    u64 ref = stress_sum();
    u32 good = 0;

    kprintf("OSM clk cfg %x, Gold RCG cfg %x\n", (u64)rd32(OSM_CLK_CFG), (u64)rd32(GOLD_RCG_CFG));
    rcg_update(OSM_CLK_CMD, OSM_CLK_CFG, (1u << 8) | 2u);       /* 200 MHz, as the Linux OSM driver sets it */
    kprintf("OSM clk 200 MHz: Gold %d MHz\n", cpu_mhz());

    for (u32 i = 0; i < sizeof steps; i++) {
        kprintf("L %d: ", (u64)steps[i]);
        if (gold_set_l(steps[i])) {
            fg = RED;
            kprintf("PLL did not lock\n");
            break;
        }
        kprintf("%d MHz, checks ", cpu_mhz());
        int ok = 0;
        for (int k = 0; k < 10; k++)
            ok += stress_sum() == ref;
        fg = ok == 10 ? GREEN : RED;
        kprintf("%d/10\n", (u64)ok);
        fg = WHITE;
        if (ok != 10)
            break;
        good = steps[i];
    }
    if (good && (rd32(PLL_GOLD + 4) & 0xff) != good)
        gold_set_l(good);
    fg = CYAN;
    kprintf("Gold final: L %d, %d MHz\n", (u64)(rd32(PLL_GOLD + 4) & 0xff), cpu_mhz());
    fg = WHITE;
}

/* ---- payload loader (format: tools/mkpayload.py) ---- */

struct payload {
    char magic[8];                              /* "LVPAYLD1" */
    u64 total_size;
    u64 virt_base, entry_va, phys_base, mem_size;
    u64 image_off, image_size, image_va, image_memsize;
    u64 adt_off, adt_size;
    u64 ramdisk_off, ramdisk_size;
    u64 reserved[2];
    char cmdline[608];
};

/* pexpert/pexpert/arm64/boot.h, xnu-8796 */
struct boot_args {
    unsigned short revision, version;
    u64 virt_base, phys_base, mem_size, top_of_kernel_data;
    struct { u64 base, display, row_bytes, width, height, depth; } video;
    u32 machine_type;
    void *device_tree;
    u32 device_tree_length;
    char cmdline[608];
    u64 boot_flags, mem_size_actual;
};

extern u8 _image_start[], _payload[];
void jump_kernel(u64 entry_pa, u64 boot_args_pa) __attribute__((noreturn));

#define PAGE_16K 0x4000UL
#define ALIGN_UP(v, a) (((v) + (a) - 1) & ~((a) - 1))

/* Write cached data back to RAM and drop it: the next stage starts with caches off. */
static void flush_range(u64 start, u64 size)
{
    for (u64 a = start & ~63UL; a < start + size; a += 64)
        __asm__ volatile("dc civac, %0" :: "r"(a));
    __asm__ volatile("dsb sy");
}

static void load_payload(void)
{
    const struct payload *p = (const struct payload *)_payload;
    const u8 *base = (const u8 *)p;
    u64 delta = p->phys_base - p->virt_base;                /* pa = va + delta */
    u64 image_pa = p->image_va + delta;
    u64 top = ALIGN_UP(image_pa + p->image_memsize, PAGE_16K);

    kprintf("payload %d KB, image -> %x\n", p->total_size >> 10, image_pa);
    memcpy((void *)image_pa, base + p->image_off, p->image_size);
    memset((void *)(image_pa + p->image_size), 0, p->image_memsize - p->image_size);

    u64 ramdisk_pa = top;
    memcpy((void *)ramdisk_pa, base + p->ramdisk_off, p->ramdisk_size);
    top = ALIGN_UP(top + p->ramdisk_size, PAGE_16K);

    u64 adt_pa = top;
    memcpy((void *)adt_pa, base + p->adt_off, p->adt_size);
    top = ALIGN_UP(top + p->adt_size, PAGE_16K);

    struct boot_args *ba = (struct boot_args *)top;
    top = ALIGN_UP(top + sizeof *ba, PAGE_16K);
    memset(ba, 0, sizeof *ba);
    ba->revision = 2;
    ba->version = 2;
    ba->virt_base = p->virt_base;
    ba->phys_base = p->phys_base;
    ba->mem_size = ba->mem_size_actual = p->mem_size;
    ba->top_of_kernel_data = top;
    ba->video.base = FB_BASE;
    ba->video.row_bytes = FB_W * 4;
    ba->video.width = FB_W;
    ba->video.height = FB_H;
    ba->video.depth = 32;
    ba->device_tree = (void *)(adt_pa - delta);             /* the kernel wants a virtual address */
    ba->device_tree_length = (u32)p->adt_size;
    memcpy(ba->cmdline, p->cmdline, sizeof ba->cmdline);

    u64 entry_pa = p->entry_va + delta;
    kprintf("entry %x boot_args %x top %x\n", entry_pa, (u64)ba, top);
    kprintf("args: %s\n", ba->cmdline);

    flush_range(image_pa, top - image_pa);
    flush_range((u64)_image_start, (u64)_payload - (u64)_image_start + p->total_size);
    flush_range(0x110000000UL, 4UL << 20);                  /* mem_fill_ms() */
    jump_kernel(entry_pa, (u64)ba);
}

static int have_payload(void)
{
    static const char magic[] = "LVPAYLD1";
    for (int i = 0; i < 8; i++)
        if (_payload[i] != (u8)magic[i])
            return 0;
    return 1;
}

/* ---- entry points ---- */

static volatile u64 gold_alive;

void gold_main(void)
{
    gold_alive = 1;
    __asm__ volatile("dsb sy");
    cpu_report("G");
    if (!((READ_SYSREG(id_aa64mmfr0_el1) >> 20) & 0xf)) {
        fg = RED;
        kprintf("Gold has no 16K granule: stop\n");
        countdown_and_reset();
    }
    kprintf("4 MB fill, MMU off: %d ms\n", mem_fill_ms());
    mmu_16k_on();
    fg = GREEN;
    kprintf("MMU 16K ON  SCTLR %x TCR %x\n", READ_SYSREG(sctlr_el1), READ_SYSREG(tcr_el1));
    fg = WHITE;
    kprintf("4 MB fill, MMU on:  %d ms\n", mem_fill_ms());
    kprintf("G clock %d MHz\n", cpu_mhz());
    gold_clock_ladder();
    kprintf("4 MB fill, final:   %d ms\n", mem_fill_ms());
    if (have_payload())
        load_payload();
    kprintf("no payload\n");
    countdown_and_reset();
}

void shim_main(const u8 *fdt, u64 load_addr)
{
    WRITE_SYSREG(sctlr_el1, READ_SYSREG(sctlr_el1) | (1 << 12));    /* I-cache: usable without the MMU */
    ISB();
    fill(0, 0, FB_W, FB_H, bg);
    fg = CYAN;
    kprintf("ios-lavender shim E2 v2\n");
    fg = WHITE;
    kprintf("loaded %x fdt %x\n", load_addr, (u64)fdt);
    fdt_report(fdt);
    cpu_report("S");
    pll_report("S", PLL_SILVER);
    pll_report("G", PLL_GOLD);

    u64 rc = smc_call(PSCI_CPU_ON, GOLD0_MPIDR, (u64)secondary_entry, 0);
    for (int n = 0; n < 300 && !gold_alive; n++)
        delay_ms(10);
    if (gold_alive)
        for (;;)
            __asm__ volatile("wfi");
    fg = RED;
    kprintf("Gold did not start, CPU_ON rc %x\n", rc);
    countdown_and_reset();
}
