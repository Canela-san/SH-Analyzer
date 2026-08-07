-cr
-m pru_core.map
-stack 0x100
-heap 0x100

/* ============================================================================== */
/* MAPA FÍSICO DE MEMÓRIA DA ARQUITETURA PING-PONG                                */
/* ============================================================================== */
MEMORY {
    PAGE 0:
      /* Memória de Instruções da PRU (8 KB) */
      PRU_IMEM       : org = 0x00000000 len = 0x00002000
      
    PAGE 1:
      /* Memória de Dados Local da PRU 0 (8 KB) */
      PRU_DMEM_0_1   : org = 0x00000000 len = 0x00002000
      
      /* Memória Compartilhada do Subsistema PRU-ICSS (12 KB) */
      /* Usada para a struct shared_control */
      PRU_SHARED_RAM : org = 0x00010000 len = 0x00003000
      
      /* Zona de Alta Velocidade Reservada na DDR (16 MB) */
      /* Endereço físico onde o Linux não toca (Ping-Pong buffers) */
      DDR_RESERVED   : org = 0x9F000000 len = 0x01000000
}

/* ============================================================================== */
/* ALOCAÇÃO DAS SEÇÕES DO COMPILADOR                                              */
/* ============================================================================== */
SECTIONS {
    /* Código executável e ponto de entrada */
    .text:_c_int00* >  0x0, PAGE 0
    .text           >  PRU_IMEM, PAGE 0
    
    /* Variáveis locais, pilha e seções padrão do C */
    .stack          >  PRU_DMEM_0_1, PAGE 1
    .bss            >  PRU_DMEM_0_1, PAGE 1 [cite: 99]
    .cio            >  PRU_DMEM_0_1, PAGE 1
    .data           >  PRU_DMEM_0_1, PAGE 1
    .rodata         >  PRU_DMEM_0_1, PAGE 1
    .sysmem         >  PRU_DMEM_0_1, PAGE 1
    .cinit          >  PRU_DMEM_0_1, PAGE 1
  
    /* Tabela obrigatória para o Linux (remoteproc) ligar a PRU */
    .resource_table >  PRU_DMEM_0_1, PAGE 1 [cite: 100]
    
    /* Mapeamento nominal das novas memórias (Evita warnings do compilador) */
    .shared_ram     >  PRU_SHARED_RAM, PAGE 1
    .ddr_ram        >  DDR_RESERVED, PAGE 1
}