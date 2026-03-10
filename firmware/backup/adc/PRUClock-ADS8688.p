// PRU1 program to provide a variable frequency clock on P8_46 (pru1_pru_r30_1) 
// that is controlled from Linux userspace by setting the PRU memory state. This
// program is executed on PRU1 and outputs the sample clock on P8_46. 

.origin 0 // start of program in PRU memory
.entrypoint START // program entry point (for a debugger)

START: 
	MOV	r1, 0x00000000 // load the base address into r1
	LBBO	r2, r1, 0, 4 // the clock delay is now loaded into r2. 4 bytes.
	MOV	r4, 0x00010000 // going to use PRU shared memory to share the state change
	MOV	r5, 0x00000000 // clear r5 to set or clear registers
// Force clock to be low in the beggining
	CLR	r30.t1 // set the sample clock signal to be low
	CLR	r5.t00
	SBBO	r5, r4, 0, 4 // store the clock state in PRU shared memory
// Flags to comunication with PRU0
	LBBO	r16, r4, 4, 4 // Write memory flag to/from PRU0
	LBBO	r18, r4, 8, 4 // Start queue flag from PRU0
// Load memory and flags from C program	
	LBBO	r6, r1, 8, 4 // LAST value added to memory 
	LBBO 	r7, r1, 12, 4 // PAST value added to memory
	LBBO	r8, r1, 16, 4 // Memory flag
// Memory address and sizes	
	LBBO	r9, r1, 20, 4 // Memory address
	LBBO	r10, r1, 24, 4 // Memory size
	MOV	r13, 0x00000000
	ADD	r13, r9, r10 // Last memory address
// Counters for updating LAST/PAST
	LBBO	r11, r9, 0, 4 // LAST counter - Load first memory address
	LBBO	r12, r13, 0, 4 // PAST counter - Last memory address
	
	QBA	ENDOFLOOP // move to comparison -- avoids duplicating code
	
MAINLOOP:
	LBBO	r14, r18, 0, 4
	QBBC	QUITQUEUE, r14.t00 // Skip program loops
	// LBBO	r15, r6, 0, 4
	// QBNE	LASTNORESET, r15, r13 // Check if the memory vector is full 
	// SBBO	r9, r6, 0, 4 // Load address in last
	// SBBO	r9, r6, 0, 4 // Load address in last - twice to balance
	// ADD	r11, r11, 4 // Increment last
	// QBA	PASTRESET
// LASTNORESET:
	// SBBO	r11, r6, 0, 4 // Store in last
	// QBNE	LASTCNTNORESET, r11, r13 // check if the memory vector is full 
	// LBBO	r11, r9, 0, 4 // Load address
	// QBA PASTRESET
// LASTCNTNORESET:
	// ADD	r11, r11, 4 // Increment last
	// LBBO	r11, r11, 0, 4 // do something to balance
// PASTRESET:
	// LBBO	r17, r7, 0, 4
	// QBNE	QUITQUEUE1, r17, r11 // check if last is approaching past
	// SET	r5.t00
	// SBBO	r5, r8, 0, 4 // Write flag in OS memory
	// QBNE	PASTNORESET, r17, r13 // If approaching check if reset is needed
	// SBBO	r9, r7, 0, 4 // store in memory
	// LBBO	r12, r9, 0, 4 // increment past 
	// CLR	r5.t00
	// SBBO	r5, r8, 0, 4 // Delete flag form os memory
	// QBA	QUITQUEUE
// PASTNORESET:
	// ADD	r12, r12, 4
	// SBBO	r12, r7, 0, 4 // Store in memory
	// CLR	r5.t00
	// SBBO	r5, r8, 0, 4 // Delete flag form os memory
	// QBA	QUITQUEUE

// QUITQUEUE1: // Wait here to balance queue
	// MOV	r0, 3 // load the delay r2 into temp r0 
	// MOV	r0, 3 // load the delay r2 into temp r0 
// DELAYONQUEUE:
	// SUB	r0, r0, 1 // decrement the counter by 1 and loop (next line)
	// QBNE	DELAYONQUEUE, r0, 0 // loop until the delay has expired (equals 0)
QUITQUEUE:
	//QBBS	END, r16.t00
	
	SET	r30.t1 // set the sample clock to be high
	SET	r5.t00 // Clear r5 bit 0
	SBBO    r5, r4, 0, 4 // store the clock state in PRU shared memory 

//	MOV	r0, r2 // load the delay r2 into temp r0 (50% duty cycle)
	MOV	r0, r2 // load the delay r2 into temp r0 (50% duty cycle) - twice to balance
//	ADD	r0, r0, 11	 // balance duty cycle by looping extra times on low
DELAYON:
	SUB	r0, r0, 1 // decrement the counter by 1 and loop (next line)
	QBNE	DELAYON, r0, 0 // loop until the delay has expired (equals 0)

	CLR	r30.t1 // set the sample clock signal to be low
	CLR	r5.t00
	SBBO	r5, r4, 0, 4 // store the clock state in PRU shared memory
	
//	MOV	r0, r2 // re-load the delay r2 into temporary r0	
	MOV	r0, r2 // re-load the delay r2 into temporary r0	
DELAYOFF:
	SUB	r0, r0, 1 // decrement the counter by 1 and loop (next line)
	QBNE	DELAYOFF, r0, 0 // loop until the delay has expired (i.e., equals 0)	
	
	QBBC	INITIALIZE, r18.t00
	//SET	r5.t00
	//SBBO	r5, r16, 0, 4 // set flag to PRU0 write to memory
INITIALIZE:	
	QBBS	ENDOFLOOP, r18.t00 // Check if program registers have been writen
	SBBO	r11, r6, 0, 4 // Initialize memory position 
	SBBO	r12, r7, 0, 4 	
	
ENDOFLOOP:                   // is the clock running? 
	LBBO	r3, r1, 4, 4 // loaded the state into r3 -- is running? 4 bytes total
	QBBS	RESETCLK, r3.t1 // If r3 bit 1 is high then reload the clock period
	QBBS	MAINLOOP, r3.t0 // If r3 bit 0 is high then the clock is running
	QBA	ENDOFLOOP // otherwise loop without toggling the clock -- i.e. clock off

RESETCLK: // clear the r3.t1 bit and write back to memory
	CLR	r3, r3.t1 // i.e., clear the reload clock flag
	SBBO	r3, r1, 4, 4 // write that value back into memory
	QBA	START // go back to the start of the program

END:				 
	HALT // halt the pru program
