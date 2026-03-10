/*  This program loads the two PRU programs into the PRU-ICSS transfers the configuration
*   to the PRU memory spaces and starts the execution of both PRU programs.
*   pressed. By Derek Molloy, for the book Exploring BeagleBone. Please see:
*        www.exploringbeaglebone.com/chapter13
*   for a full description of this code example and the associated programs.
*/

#include <stdio.h>
#include <stdlib.h>
#include <prussdrv.h>
#include <pruss_intc_mapping.h>

#define ADC_PRU_NUM        0   // using PRU0 for the ADC capture
#define CLK_PRU_NUM        1   // using PRU1 for the sample clock
#define MMAP0_LOC   "/sys/class/uio/uio0/maps/map0/"
#define MMAP1_LOC   "/sys/class/uio/uio0/maps/map1/"

enum FREQUENCY {// measured and calibrated, but can be calculated
	FREQ_12_5MHz =  1,
	FREQ_6_25MHz =  5,
	FREQ_5MHz    =  7,
	FREQ_3_85MHz = 10,
	FREQ_1MHz   =  45,
	FREQ_500kHz =  95,
	FREQ_250kHz = 245,
	FREQ_100kHz = 485, // 485*2 + 30(Instructions cycles) = 1000 instructions -> 100k Hz for 2 cycles
	FREQ_25kHz = 1995,
	FREQ_10kHz = 4995,
	FREQ_5kHz =  9995,
	FREQ_2kHz = 24995,
	FREQ_1kHz = 49995
};

enum CONTROL {
	PAUSED = 0,
	RUNNING = 1,
	UPDATE = 3
};

// Short function to load a single unsigned int from a sysfs entry
unsigned int readFileValue(char filename[]){
	FILE* fp;
	unsigned int value = 0;
	fp = fopen(filename, "rt");
	fscanf(fp, "%x", &value);
	fclose(fp);
	return value;
}

int main (void)
{
	if(getuid()!=0){
	  printf("You must run this program as root. Exiting.\n");
	  exit(EXIT_FAILURE);
	}
        // Disable PRU and close memory mappings
        //prussdrv_pru_disable(ADC_PRU_NUM);
        //prussdrv_pru_disable(CLK_PRU_NUM);

	// Initialize structure used by prussdrv_pruintc_intc
	// PRUSS_INTC_INITDATA is found in pruss_intc_mapping.h
	tpruss_intc_initdata pruss_intc_initdata = PRUSS_INTC_INITDATA;

	// Read in the location and address of the shared memory. This value changes
	// each time a new block of memory is allocated.
	unsigned int timerData[7];
	timerData[0] = FREQ_100kHz;
	timerData[1] = RUNNING;
	timerData[2] = 0x00000000; // Last
	timerData[3] = 0x00000000; // Past
	timerData[4] = 0x00000000; // Flag
	timerData[5] = readFileValue(MMAP1_LOC "addr");
	timerData[6] = readFileValue(MMAP1_LOC "size");

	printf("The PRU clock state is set as period: %d (0x%x) and state: %d\n", timerData[0], timerData[0], timerData[1]);
	unsigned int PRU_data_addr = readFileValue(MMAP0_LOC "addr");
	printf("-> the PRUClock memory is mapped at the base address: %x\n", (PRU_data_addr + 0x2000));
	printf("-> the PRUClock on/off state is mapped at address: %x\n", (PRU_data_addr + 0x10000));

	// data for PRU0 based on the MCPXXXX datasheet
	unsigned int spiData[7];
	spiData[0] = 0xA0000001; // Command register
	spiData[1] = readFileValue(MMAP1_LOC "addr");
	spiData[2] = readFileValue(MMAP1_LOC "size");
	// ProgramCommand = 0x(regAddr*2+1) followed by program
	spiData[3] = 0x03800000; // Channel selection for power- channel 0 is selectected
	spiData[4] = 0x057F0000;// Channel 0 is on
	spiData[5] = 0x07010000; // 0x07030000 can be used to read 8 more bits @ MISO
	spiData[6] = 0x19010000; // Channel 0. Voltage range selected to be +- 5.12V i.e. sensor can measure up$

	//spiData[4] = 0x07010000; // 0x07030000 can be used to read 8 more bits @ MISO
	//spiData[6] = 0x0B010000; // Channel 0. Voltage range selected to be +- 5.12V i.e. sensor can measure up to$
	//spiData[7] = 0x0D000000; // Voltage range selected to be +- 10.24V i.e. sensor can measure up to 127Vrms
	//spiData[8] = 0x0F000000;
	//spiData[9] = 0x11000000;
	//      spiData[13] = 0x13000000 not used; Channel 4 not used
	//spiData[10] = 0x15010000;
	//spiData[11] = 0x17010000;
	//spiData[12] = 0x19010000;
	printf("Sending the SPI Control Data: 0x%x\n", spiData[0]);
	printf("The DDR External Memory pool has location: 0x%x and size: 0x%x bytes\n", spiData[1], spiData[2]);
	int numberSamples = spiData[2]; // Divided by 2 because it is 2 bytes per sample and allocated space is 2MB
	printf("-> this space has capacity to store %d 16-bit samples (max)\n", numberSamples);

        printf("-> the PRUADC memory is mapped at the base address: %x\n", (PRU_data_addr));

	// Allocate and initialize memory
	prussdrv_init ();
	prussdrv_open (PRU_EVTOUT_0);

	// Write the address and size into PRU0 Data RAM0. You can edit the value to
	// PRUSS0_PRU1_DATARAM if you wish to write to PRU1
	prussdrv_pru_write_memory(PRUSS0_PRU0_DATARAM, 0, spiData, 28);  // spi code
	prussdrv_pru_write_memory(PRUSS0_PRU1_DATARAM, 0, timerData, 28); // sample clock
	// NOTE: The timerData is mapped at data ram 0, therefore it is accessible bia 0000_2000

	// Map the PRU's interrupts
	prussdrv_pruintc_init(&pruss_intc_initdata);

	// Load and execute the PRU program on the PRU
	prussdrv_exec_program (ADC_PRU_NUM, "./PRUADC-ADS8688.bin");
	prussdrv_exec_program (CLK_PRU_NUM, "./PRUClock-ADS8688.bin");
	printf("EBBClock PRU1 program now running (%d)\n", timerData[0]);

	// Wait for event completion from PRU, returns the PRU_EVTOUT_0 number
	int n = prussdrv_pru_wait_event (PRU_EVTOUT_0);
	printf("EBBADC PRU0 program completed or ERRO programming registers, event number %d.\n", n);

	// Disable PRU and close memory mappings
	prussdrv_pru_disable(ADC_PRU_NUM);
	prussdrv_pru_disable(CLK_PRU_NUM);

	prussdrv_exit ();
	return EXIT_SUCCESS;
}

