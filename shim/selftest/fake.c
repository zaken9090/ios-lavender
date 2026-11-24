/*
 * Loader self-test: stands in for the kernel. Entered like XNU (EL1, MMU off, x0 = boot_args)
 * and paints one band per check, green = pass, red = fail:
 *   1 boot_args revision/version      2 running where virt_base/phys_base say
 *   3 command line passed             4 MMU off and top_of_kernel_data above us
 * Then waits 90 s and resets through PSCI.
 */
typedef unsigned int u32;
typedef unsigned long u64;

#define IMAGE_VA 0xfffffff007004000UL   /* default --image-va of tools/mkpayload.py */

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

#define READ_SYSREG(name) ({ u64 v_; __asm__ volatile("mrs %0, " #name : "=r"(v_)); v_; })

static void band(const struct boot_args *ba, int n, int ok)
{
    volatile u32 *fb = (volatile u32 *)ba->video.base;
    u64 stride = ba->video.row_bytes / 4;
    for (u64 y = 1500 + (u64)n * 200; y < 1660 + (u64)n * 200 && y < ba->video.height; y++)
        for (u64 x = 0; x < ba->video.width; x++)
            fb[y * stride + x] = ok ? 0xff00c000 : 0xffff0000;
}

void fake_main(const struct boot_args *ba, u64 self_pa)
{
    static const char want[] = "selftest";
    int cmd_ok = 1;
    for (int i = 0; i < 8; i++)
        cmd_ok &= ba->cmdline[i] == want[i];

    band(ba, 0, ba->revision == 2 && ba->version == 2);
    band(ba, 1, self_pa == IMAGE_VA - ba->virt_base + ba->phys_base);
    band(ba, 2, cmd_ok);
    band(ba, 3, !(READ_SYSREG(sctlr_el1) & 1) && ba->top_of_kernel_data > self_pa &&
                ba->top_of_kernel_data < ba->phys_base + ba->mem_size);

    u64 end = READ_SYSREG(cntvct_el0) + READ_SYSREG(cntfrq_el0) * 90;
    while (READ_SYSREG(cntvct_el0) < end)
        ;
    register u64 x0 __asm__("x0") = 0x84000009UL;       /* PSCI SYSTEM_RESET */
    __asm__ volatile("smc #0" : "+r"(x0));
    for (;;)
        ;
}

__asm__(
    ".section .head, \"ax\"\n"
    ".globl _start\n"
    "_start:\n"
    "    adr  x1, _start\n"
    "    add  x2, x1, #0x40000\n"       /* stack inside our own image_memsize */
    "    mov  sp, x2\n"
    "    b    fake_main\n");
