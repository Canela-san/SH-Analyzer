// PRU0 program to communicate to the ADS8688 family of SPI ADC ICs. The program
// generates the SPI signals that are required to receive samples. To use this
// program as is, use the following wiring configuration:
//   Chip Select (CS):   P9_28    pr1_pru0_pru_r30_5  r30.t3
//   MOSI            :   P9_29    pr1_pru0_pru_r30_1  r30.t1
//   MISO            :   P9_30    pr1_pru0_pru_r31_3  r31.t2
//   CLK             :   P9_31    pr1_pru0_pru_r30_2  r30.t0
//   Sample Clock    :   P8_46    pr1_pru1_pru_r30_1  -- for testing only
.setcallreg r29.w2 // set a non-default CALL/RET register - The default register is R30.w0
.origin 0 // start of program in PRU memory
.entrypoint START // program entry point (for a debugger)

#define PRU0_R31_VEC_VALID 32 // Enable communication by setting bit 5 (i.e. 32 base 10) allow an output event to be sent to lINUX.
#define PRU_EVTOUT_0 3 // The event #3 corresponds to event out 0 (code completion). Event Interface Mapping (R31): PRU System Events
// Constants from the ADS8688 datasheet
#define TIME_CLOCK 6 // Max period = 59ns -> T_hi and t_lo = 30ns = 6 clocks (min) - bit banging alrady takes 6 cyles, min = 0
// Program register variables
#define PROG_REGISTER_NUM 4 // Number of program registers
#define PROG_REGISTER_OFFSET 12 // Memory offset to program registers

START:
// Enable the OCP master port - allows transfer of data to Linux userspace
	LBCO    r0, C4, 4, 4 // load SYSCFG(c4 - register of 4 bytes - Power IDLE and STANDBY modes) 
	CLR     r0, r0, 4 // clear bit 4 of r0 (STANDBY_INIT) - Disable standby and enable high Performance Interface/OCP Master port for accessing external memories).
	SBCO    r0, C4, 4, 4 // store the modified r0 back at the SYSCFG reg, enabling OCP ports

// Configure read and write
	MOV     r1, 0x00000000 // load the RAM_0 to read the program and commands to be send
	MOV     r7, 0xFF00FFFF // the bit mask to use on the returned data, containing the channel 
	LBBO    r8, r1, 4, 4 // linux address that is passed into r8 to store sample values
	LBBO    r9, r1, 8, 4 // load the size that is passed into r9 the number of samples to take
	MOV     r3, 0x00000000 // clear r3 to receive the response from the ADS8688 - MISO
	CLR     r30.t1 // clear the data out line - MOSI

// Initialize program registers for ADS8688
	MOV	r10, 0x0000FF00 // Bit mask of the program register response
	MOV	r11, PROG_REGISTER_NUM // Number of program registers
	MOV	r12, PROG_REGISTER_OFFSET // Offset to read program words to be send to ADS8688
// Load memory access to sync PRUs
	MOV	r5, 0x00010000 // load the shared RAM address to r5
	LBBO	r14, r5, 4, 4 // Write memory flag to/from PRU1
	MOV	r15, 0x00000000 // Used to clear the flags
	CLR r15.t00
	SBBO	r15, r14, 0, 4
	LBBO	r16, r5, 8, 4 // Start queue flag to PRU1
	SBBO	r15, r16, 0, 4 
	
SAMPLE_WAIT_LOW_INIT: // need to wait here if the sample clock has not gone low
	LBBO	r6, r5, 0, 4 // load the value in PRU1 sample clock address r5 into r6
	QBNE	SAMPLE_WAIT_LOW_INIT, r6, 0 // wait until the sample clock goes low (just in case)
	
ADS_CONFIG:		
	LBBO	r2, r1, r12, 4 // load the configuration command
SAMPLE_WAIT_HIGH_CONFIG: // wait until the sample clock goes high       
	LBBO	r6, r5, 0, 4
	QBNE	SAMPLE_WAIT_HIGH_CONFIG, r6, 1

	CLR	r30.t3 // set the CS line low (active low)
	MOV	r4, 36 // going to write/read 36 bits - containing channel address
// Write/Read to SPI
SPICLK_ADS:
	SUB	r4, r4, 1 // count down through the bits
	CALL	SPICLK // repeat call the SPICLK procedure until all 24-bits written/read
	QBNE	SPICLK_ADS, r4, 0
// Procedures after end of program register write/read
	SET	r30.t3 // pull the CS line high (end of configuration)
	LSR	r3, r3, 5 // SPICLK shift right five times to enable comparison
	AND	r3, r3, r10 // AND the data with mask to give only the MISO response to comparison
// Check program register 
	LBBO	r2, r1, r12, 4 // Load the configuration command again 
	LSR	r2, r2, 8 // Shift 8 bits to allow comparison
	AND	r2, r2, r10 // Get only the program command
	QBNE	END, r2, r3 // Exit if program is incorrect
	ADD	r12, r12, 4 // Proceed to the next progam register
	
SAMPLE_WAIT_LOW_CONFIG:
	LBBO    r6, r5, 0, 4 // load the value in PRU1 sample clock address r5 into r6
	QBNE	SAMPLE_WAIT_LOW_CONFIG, r6, 0 // wait until the sample clock goes low (just in case)
	SUB	r11, r11, 1
	QBNE	ADS_CONFIG, r11, 0

// Continue to sample
	MOV	r3, 0x00000000 // Clear to receive the response from the ADS8688 - MISO
	CLR	r30.t1 // clear the data out line - MOSI
	
GET_SAMPLE:
	LBBO    r2, r1, 0, 4 // the MCP3XXX states are now stored in r2 -- need the 16 MSBs
	CLR	r15.t00	
	SBBO	r15, r14, 0, 4 // Clear the flag comming from pru1
	
SAMPLE_WAIT_HIGH:
	LBBO    r6, r5, 0, 4// load the value at address r5 into r6
	QBNE    SAMPLE_WAIT_HIGH, r6, 1 // Wait until the sample clock goes high
// ATENÇÂO AQUI
// Start circular queue	
	QBBS	BIT_BANG, r16.t00 // If queue is not set
	SET	r15.t00
	SBBO	r15, r16, 0, 4 // Start circular queue in PRU1
BIT_BANG:	
	CLR	r30.t3 // set the CS line low (active low)
	MOV	r4, 36 // going to write/read 24 bits (3 bytes)
// Write/Read SPI
SPICLK_BIT:
	SUB	r4, r4, 1 // count down through the bits
	CALL	SPICLK // repeat call the SPICLK procedure until all bits written/read
	QBNE	SPICLK_BIT, r4, 0

	SET	r30.t3 // pull the CS line high (end of sample)
// Check if reset command is sent in memory
	LBBO	r13, r1, 0, 4 // load reset command from memory
	QBBC    END, r13.t00 // Stop if reset = 0
	
	LSL	r3, r3, 3 // SPICLK shifts left 3 times to complete byte
	MOV	r3.b3, r3.b0 // Channel bits are shifted to the MSB
	LSR	r3, r3, 8 // Frame is shifted right to yield LSB as the measure
	MOV	r3.b3, r3.b2 // Channel bits are shifted again to the MSB
	AND	r3, r3, r7 // AND the data with mask to give only the LSBs

// Store data sample value in memory
	SUB	r9, r9, 4 // reducing the number of samples - 4 bytes per sample
//SAMPLE_WAIT_HIGH_MEM: // wait until the PRU1 flag goes high
	//LBBO	r6, r14, 0, 4 // load the value at address r5 into r6
	//QBBC	SAMPLE_WAIT_HIGH_MEM, r6.t00 // Wait until the sample clock goes high

	SBBO	r3, r8, 0, 4 // store the value r3 in memory
	ADD	r8, r8, 4 // shifting by 4 bytes - 4 bytes per sample
	QBEQ    RESTART_COUNTER, r9, 0 // have taken the full set of samples

//SAMPLE_WAIT_LOW:                 // need to wait here if the sample clock has not gone low
//	LBBO    r6, r5, 0, 4     // load the value in PRU1 sample clock address r5 into r6
//	QBNE    SAMPLE_WAIT_LOW, r6, 0 // wait until the sample clock goes low (just in case)

	QBA	GET_SAMPLE
RESTART_COUNTER:
	LBBO    r8, r1, 4, 4 // linux address that is passed into r8 to store sample values
	LBBO	r9, r1, 8, 4 // load the number of samples to take
//	MOV	r3, 0x00000000 // Clear r3 to receive the response from the ADS8688 - MISO	

	QBA	GET_SAMPLE
	
END:
	MOV	r31.b0, PRU0_R31_VEC_VALID | PRU_EVTOUT_0
	HALT // End of program -- below are the "procedures"
		
// This procedure applies an SPI clock cycle to the SPI clock and on the rising edge of the clock
// it writes the current MSB bit in r2 (i.e. r31) to the MOSI pin. On the falling edge, it reads
// the input from MISO and stores it in the LSB of r3.

SPICLK: // 9 cycles if r0=0
// Set clock high and write to MOSI
	SET	r30.t0 // set the clock high
	QBBC	DATAOUTLOW, r2.t31 // Branch to DATALOW if bit r2.t31 (1st MOSI bit) is clear 
	SET	r30.t1
	QBA	DATACONTD
DATAOUTLOW:
	CLR	r30.t1		 
	MOV	r0, TIME_CLOCK   
DATACONTD:
	LSL	r2, r2, 1 //Bit 31 shifted left

	MOV	r0, TIME_CLOCK // time for clock high -- assuming clock low before cycle
CLKHIGH_WRITE:
	SUB	r0, r0, 1 // decrement the counter by 1 and loop (next line)
	QBNE    CLKHIGH_WRITE, r0, 0 // check the count		
	MOV	r0, TIME_CLOCK // time for clock low	
// Set low low and read from MISO
	CLR	r30.t0 // set the clock low	
	QBBC	DATAINLOW, r31.t2
	OR	r3, r3, 0x00000001
DATAINLOW:
	LSL	r3, r3, 1
CLKLOW_READ:
	SUB	r0, r0, 1 // decrement the counter by 1 and loop (next line)
	QBNE	CLKLOW_READ, r0, 0 // check if the count is still low
	RET
	
