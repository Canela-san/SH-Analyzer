/* pru_adc.c - Firmware com Sonda de Diagnóstico e Clock Seguro */

#include <stdint.h>
#include <pru_ctrl.h>
#include "resource_table_empty.h"

#define SCLK_PIN  (1 << 0)  // P9_31
#define MOSI_PIN  (1 << 1)  // P9_29
#define MISO_PIN  (1 << 2)  // P9_30
#define CS_PIN    (1 << 3)  // P9_28

#define PRU_CFG_SYSCFG (*(volatile uint32_t *)0x00026004)
#define SHARED_RAM_ADDR 0x00010000 
#define NUM_SAMPLES     50

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
        __delay_cycles(50); // Clock mais lento para atravessar o ADuM3150
        
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

    PRU_CFG_SYSCFG &= ~(1 << 4);

    __R30 |= CS_PIN;    
    __R30 &= ~SCLK_PIN; 
    __R30 &= ~MOSI_PIN; 
    __delay_cycles(100000); 

    /* Inicialização do ADS8688 */
    spi_transfer(0x85000000); // Reset
    __delay_cycles(200000); 
    
    spi_transfer(0x0D010000); // Faixa +-5.12V (CH1)
    spi_transfer(0xC4000000); // Seleciona CH1 Manual
    __delay_cycles(10000); 

    /* Loop de Aquisição com Armadilha */
    for(i = 0; i < NUM_SAMPLES; i++) {
        raw_data = spi_transfer(0x00000000); 
        sample = (raw_data >> 16) & 0xFFFF;
        
        /* DETECTOR DE HARDWARE: 
         * Se o hardware mandar zero absoluto, injetamos 32768 (0.00 V).
         * Se o Python exibir 0.00 V, o defeito é na fiação/isolador/config-pin.
         */
        if(sample == 0) {
            ddr_mem[i] = 32768 + i; 
        } else {
            ddr_mem[i] = sample;
        }
        
        __delay_cycles(100); 
    }

    __halt();
}