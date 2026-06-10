#include <stdint.h>

// Tabela de Recursos OBRIGATÓRIA para o driver remoteproc do Linux
struct resource_table {
    uint32_t ver;
    uint32_t num;
    uint32_t reserved[2];
};
#pragma DATA_SECTION(resource_table, ".resource_table")
#pragma RETAIN(resource_table)
struct resource_table resource_table = { 1, 0, {0, 0} };

// Endereços base e offsets do banco GPIO3 do AM335x
#define GPIO3_BASE        0x481AE000
#define GPIO_OE           0x134 
#define GPIO_CLEARDATAOUT 0x190
#define GPIO_SETDATAOUT   0x194

#define SCLK_PIN (1 << 14) // P9_31
#define MOSI_PIN (1 << 16) // P9_30
#define CS_PIN   (1 << 17) // P9_28

volatile uint32_t *gpio3_oe    = (uint32_t *)(GPIO3_BASE + GPIO_OE);
volatile uint32_t *gpio3_clear = (uint32_t *)(GPIO3_BASE + GPIO_CLEARDATAOUT);
volatile uint32_t *gpio3_set   = (uint32_t *)(GPIO3_BASE + GPIO_SETDATAOUT);

void delay_cycles(uint32_t cycles) {
    while(cycles--) __delay_cycles(1);
}

void main(void) {
    // Habilita a porta OCP Master (bit 4 do SYSCFG)
    volatile uint32_t *pru_syscfg = (uint32_t *)0x26004;
    *pru_syscfg &= ~(1 << 4);

    // Forçando a direção dos pinos como SAÍDA (Hardware puro)
    *gpio3_oe &= ~(SCLK_PIN | MOSI_PIN | CS_PIN);

    uint8_t test_byte = 0xAA; 
    int i;

    while(1) {
        *gpio3_set = CS_PIN; 
        delay_cycles(100000); 
        
        *gpio3_clear = CS_PIN; 
        delay_cycles(10000);

        for(i = 7; i >= 0; i--) {
            if((test_byte >> i) & 1) *gpio3_set = MOSI_PIN;
            else *gpio3_clear = MOSI_PIN;
            delay_cycles(5000);

            *gpio3_set = SCLK_PIN;
            delay_cycles(10000);

            *gpio3_clear = SCLK_PIN;
            delay_cycles(5000);
        }

        *gpio3_set = CS_PIN;
        delay_cycles(50000000); 
    }
}