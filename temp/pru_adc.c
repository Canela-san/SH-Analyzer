/* pru_adc.c - Firmware com Auto-Wakeup via GPIO 125 e Sonda de Diagnóstico */

#include <stdint.h>
#include <pru_ctrl.h>
#include "resource_table_empty.h"

/* Pinos SPI (Alinhados com o hardware da SPI1 do BeagleBone) */
#define SCLK_PIN  (1 << 0)  // P9_31
#define MISO_PIN  (1 << 1)  // P9_29 (Era MOSI, agora é MISO - Entrada)
#define MOSI_PIN  (1 << 2)  // P9_30 (Era MISO, agora é MOSI - Saída)
#define CS_PIN    (1 << 3)  // P9_28

/* Registradores do Sistema e PRU */
#define PRU_CFG_SYSCFG (*(volatile uint32_t *)0x00026004)
#define SHARED_RAM_ADDR 0x00010000 
#define NUM_SAMPLES     50

/* --- REGISTRADORES PARA CONTROLAR O GPIO 125 (Banco 3, Pino 29) --- */
/* Clock Module para garantir que o GPIO3 esteja energizado */
#define CM_PER_GPIO3_CLKCTRL (*(volatile uint32_t *)0x44E000B4)

/* Endereços físicos do Banco GPIO3 */
#define GPIO3_BASE         0x481AE000
#define GPIO3_OE           (*(volatile uint32_t *)(GPIO3_BASE + 0x134)) // Configura Entrada/Saída
#define GPIO3_SETDATAOUT   (*(volatile uint32_t *)(GPIO3_BASE + 0x194)) // Aplica Nível ALTO
#define GPIO3_CLEARDATAOUT (*(volatile uint32_t *)(GPIO3_BASE + 0x190)) // Aplica Nível BAIXO

volatile register uint32_t __R30;
volatile register uint32_t __R31;

/* Transferência SPI Mais Lenta (Segura para Isoladores) */
uint32_t spi_transfer(uint32_t tx_data) {
    uint32_t rx_data = 0;
    int i; 
    
    __R30 &= ~CS_PIN;
    __delay_cycles(100); 
    
    for(i = 31; i >= 0; i--) {
        if(tx_data & (1 << i)) {
            __R30 |= MOSI_PIN;
        } else {
            __R30 &= ~MOSI_PIN;
        }
        __delay_cycles(50); 
        
        __R30 |= SCLK_PIN;
        __delay_cycles(50); 
        
        rx_data <<= 1;
        if(__R31 & MISO_PIN) {
            rx_data |= 1;
        }
        
        __R30 &= ~SCLK_PIN;
        __delay_cycles(50);
    }
    
    __delay_cycles(100);
    __R30 |= CS_PIN; 
    __delay_cycles(200); 
    
    return rx_data;
}

void main(void) {
    volatile uint16_t *ddr_mem = (volatile uint16_t *)SHARED_RAM_ADDR;
    uint32_t i;
    uint32_t raw_data;
    uint16_t sample;

    /* 1. Habilitar o OCP Master port para acessar as memórias externas da placa */
    PRU_CFG_SYSCFG &= ~(1 << 4);

    /* 2. ACORDAR O ADC VIA GPIO 125 */
    CM_PER_GPIO3_CLKCTRL = 0x02;    // Garante que o módulo GPIO3 tem energia para receber comandos
    GPIO3_OE &= ~(1 << 29);         // Limpa o bit 29 (0 = Saída)
    GPIO3_SETDATAOUT = (1 << 29);   // Define o bit 29 como Nível Alto (1 = 3.3V)
    
    /* Dá um tempo para o isolador e o ADC estabilizarem a energia internamente */
    __delay_cycles(2000000);

    /* 3. Inicializar Pinos SPI da PRU */
    __R30 |= CS_PIN;    
    __R30 &= ~SCLK_PIN; 
    __R30 &= ~MOSI_PIN; 
    __delay_cycles(100000); 

    /* 4. Inicialização do ADS8688 */
    spi_transfer(0x85000000); // Reset do ADS via SPI
    __delay_cycles(200000); 
    
    spi_transfer(0x0D010000); // Faixa +-5.12V (CH1)
    spi_transfer(0xC4000000); // Seleciona CH1 Manual
    __delay_cycles(10000); 

    /* 5. Loop de Aquisição */
    for(i = 0; i < NUM_SAMPLES; i++) {
        raw_data = spi_transfer(0x00000000); 
        sample = (raw_data >> 16) & 0xFFFF;
        
        /* DETECTOR DE HARDWARE (Mantido para segurança) */
        if(sample == 0) {
            ddr_mem[i] = 32768 + i; 
        } else {
            ddr_mem[i] = sample;
        }
        
        __delay_cycles(100); 
    }

    __halt();
}