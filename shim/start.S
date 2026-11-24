/* Entry point. ABL treats the image as a Linux arm64 kernel: header below, x0 = device tree. */

    .section .head, "ax"
    .globl _start
_start:
    b       real_start
    .long   0
    .quad   0x80000                 /* text_offset from the start of RAM */
    .quad   _image_size
    .quad   0xa                     /* little endian, 4K pages, 2M-aligned anywhere */
    .quad   0, 0, 0
    .long   0x644d5241              /* "ARM\x64" */
    .long   0

real_start:
    msr     daifset, #0xf
    mov     x20, x0
    adrp    x1, _stack_top
    add     x1, x1, :lo12:_stack_top
    mov     sp, x1
    adrp    x1, __bss_start
    add     x1, x1, :lo12:__bss_start
    adrp    x2, __bss_end
    add     x2, x2, :lo12:__bss_end
1:  cmp     x1, x2
    b.hs    2f
    str     xzr, [x1], #8
    b       1b
2:  adrp    x1, vectors
    add     x1, x1, :lo12:vectors
    mrs     x2, CurrentEL
    cmp     x2, #0x8
    b.eq    3f
    msr     vbar_el1, x1
    b       4f
3:  msr     vbar_el2, x1
4:  isb
    mov     x0, x20
    adr     x1, _start              /* address we really run at */
    bl      shim_main
5:  wfi
    b       5b

/* Entry of a core started with PSCI CPU_ON: EL1, MMU off, x0 = context id. */
    .globl secondary_entry
secondary_entry:
    msr     daifset, #0xf
    adrp    x1, _gold_stack_top
    add     x1, x1, :lo12:_gold_stack_top
    mov     sp, x1
    adrp    x1, vectors
    add     x1, x1, :lo12:vectors
    msr     vbar_el1, x1
    isb
    bl      gold_main
1:  wfi
    b       1b

/* x0 = function id, x1..x3 = arguments */
    .globl smc_call
smc_call:
    smc     #0
    ret

    .macro  vec n
    .balign 0x80
    mov     x0, #\n
    b       exc_common
    .endm

    .balign 0x800
vectors:
    vec 0
    vec 1
    vec 2
    vec 3
    vec 4
    vec 5
    vec 6
    vec 7
    vec 8
    vec 9
    vec 10
    vec 11
    vec 12
    vec 13
    vec 14
    vec 15

exc_common:
    adrp    x4, _exc_stack_top
    add     x4, x4, :lo12:_exc_stack_top
    mov     sp, x4
    mrs     x4, CurrentEL
    cmp     x4, #0x8
    b.eq    1f
    mrs     x1, esr_el1
    mrs     x2, elr_el1
    mrs     x3, far_el1
    b       2f
1:  mrs     x1, esr_el2
    mrs     x2, elr_el2
    mrs     x3, far_el2
2:  bl      exc_report
3:  wfi
    b       3b
