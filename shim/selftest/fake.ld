ENTRY(_start)
SECTIONS
{
    . = 0;
    .text : { KEEP(*(.head)) *(.text .text.*) *(.rodata .rodata.*) *(.data .data.*) }
    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) *(.ARM.*) }
}
