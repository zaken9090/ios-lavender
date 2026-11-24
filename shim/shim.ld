ENTRY(_start)
SECTIONS
{
    . = 0x80080000;
    _image_start = .;
    .text   : { KEEP(*(.head)) *(.text .text.*) }
    .rodata : { *(.rodata .rodata.*) }
    .data   : { *(.data .data.*) }
    . = ALIGN(16);
    __bss_start = .;
    .bss    : { *(.bss .bss.* COMMON) }
    . = ALIGN(16);
    __bss_end = .;
    . += 0x10000;
    _stack_top = .;
    . += 0x10000;
    _gold_stack_top = .;
    . += 0x4000;
    _exc_stack_top = .;
    . = ALIGN(4096);
    _payload = .;                   /* build.ps1 pads the Image to here and appends the payload */
    _image_size = . - _image_start; /* build.ps1 adds the payload size in the header */
    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) *(.ARM.*) }
}
