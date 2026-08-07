-cr
-m pru_core.map
-stack 0x100
-heap 0x100

MEMORY {
    PAGE 0:
      PRU_IMEM : org = 0x00000000 len = 0x00002000
    PAGE 1:
      PRU_DMEM_0_1 : org = 0x00000000 len = 0x00002000
}

SECTIONS {
    .text:_c_int00* >  0x0, PAGE 0
    .text           >  PRU_IMEM, PAGE 0
    .stack          >  PRU_DMEM_0_1, PAGE 1
    .bss            >  PRU_DMEM_0_1, PAGE 1
    .cio            >  PRU_DMEM_0_1, PAGE 1
    .data           >  PRU_DMEM_0_1, PAGE 1
    .rodata         >  PRU_DMEM_0_1, PAGE 1
    .sysmem         >  PRU_DMEM_0_1, PAGE 1
    .cinit          >  PRU_DMEM_0_1, PAGE 1
    .resource_table >  PRU_DMEM_0_1, PAGE 1
}