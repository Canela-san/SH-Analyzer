//============================================================================
// Name		: iec61000-4.cpp
// Author	: Hildo Guillardi Júnior
// Copyright: Code can't not be freely distributed and final software use under article authorship.
// Description: Evaluate some electrical index follow IEC6100-4 and output as a XML format.
//============================================================================
#define __VERSION__ "0.1.0"


#include <sstream>
#include <iostream>
#include <queue>
#include <ctime>
#include <string>

using namespace std;

#ifdef _DEBUG // Define `_DEBUG` in "Project>>Properties>>Build>>PRU complier>>Predefined symbols".
#endif // End of __DEBUG__

#include <sys/stat.h>
#include <sys/types.h>
#include <fcntl.h> // To open the pipe file with the no-wait constant definition.
#include <unistd.h> // To manipulate the pipe file.
#include <stdio.h> // To delete the file when the software are finishing.

#include "./iniparser/iniparser.h" // Use a MIT package for parse INI files.


// Configurations. libraries and macros used for generation of random numbers
#include <stdlib.h> // Functions: srand, rand and `RAND_MAX` definition.
//#include <time.h> //Functions: time (for random seed `srand(time(NULL));`).
#define getrandom_minmax(min, max) (float)rand()/((float)RAND_MAX/(max-min))+min // Generate a random number between `min` and `max`.
#define getrandom_avgvar(avg, var) (float)rand()/((float)RAND_MAX/(2*var))+avg // Generate a random number around `avg` with variation `var`.


#define SSTR( x ) static_cast<std::ostringstream &>( \
		( std::ostringstream() << std::dec << x ) ).str() // Create a C++ string constant location in the software.

#define FIFO_FILE "./iec6100-4.fifo" // Communication channel.
#define FIFO_SIZE 6 // Keep just the last `FIFO_SIZE` messages if the file `FIFO_FILE`is not being read.

#define CONF_FILE "./iec6100-4.conf" // Configuration file used to save gain, offset and hardware definitions.


// Execution modes.
int executeNormal(void);
int executeCalibrate(void);
int executeEmulation(void);

// Global variables (configurations in general).
const char *channelsUsed;
float channelsOffsets[8];
float channelsGain[8];


// -------------------------- Main code and entry point --------------------------

int main(int argc, char** argv) {
	if(argc==2 && (std::string(argv[1])=="--help" || std::string(argv[1])=="-h")) {
		cout << "Software to evaluate some electrical index follow IEC6100-4 capture by the PRUs from the ADCs and output as a XML format." << endl
			<< "--help, -h\t\tFor help;" << endl
			<< "--version, -v\t\tFor version / authorship information;" << endl
			<< "--emulate, -e\t\tEmulate the measure acquition (generate random data);" << endl
			<< "--data, -d\t\tTo create a file data with the RAW measures (use the meter as signal acquisiton equipment);" << endl
				<< "--decimate [int]\tUse decimate the data to save in the file on the `--data`mode;" << endl
				<< "\t--time, -t \tUse to set how long the software will stay on `--data` mode;" << endl
					<< "\t\tS\tFor acquire `S` seconds;" << endl
					<< "\t\tH:M:S\tFor acquire `H` hours, `M` minutes and `S` seconds;" << endl
				<< "\t--start\t\tSame as `--time` but to start an acquire;" << endl
				<< "\t--end\t\tSame as `--time` but to end an acquire;" << endl
			<< "--calibrate, -cal\tTo initiate calibration procedure (it's necessary know the true values of voltage and current being measured, use multimeter in the phases);" << endl
			<< "Use no input for the normal software behavior." << endl;
		return 0;
	}
	else if(argc==2 && (std::string(argv[1])=="--version" || std::string(argv[1])=="-v")) {
		cout << "IEC6100-4 Linux evaluate software" << endl
			<< "Version: " << SSTR(__VERSION__) << endl
			<< "Author: Hildo Guillardi Junior" << endl;
		return 0;
	}
	else if(argc==2 && (std::string(argv[1])=="--calibrate" || std::string(argv[1])=="-cal")) {
		return executeCalibrate(); // Start the calibration procedure.
	}
	else if(argc==2 && (std::string(argv[1])=="--data" || std::string(argv[1])=="-d")) {
		
		
	}
	else if(argc==2 && (std::string(argv[1])=="--emulate" || std::string(argv[1])=="-e")) {
		return executeEmulation(); // Software emulation, generate random values.
	}
	else if(argc==1) {
		return executeNormal(); // Normal execution of the software.
	}
	else {
		cout << "Not recognize parameter(s)." << endl;
		return 1;
	}
}

int executeEmulation(void) {
	cout << "Starting emulation procedure." << endl;
	std::queue<std::string> internalFIFO;

	int status;

	status = mkfifo(FIFO_FILE, 0666);
	//printf("%i", status);
	if(status == -1)
		cout << "FIFO file '" << SSTR(FIFO_FILE) << "' created previous." << endl;
	else if(status < 0) {
		cout << "FIFO file '" << SSTR(FIFO_FILE) << "' can not be created." << endl;
		return 1;
	}
	else
		cout << "FIFO file '" << SSTR(FIFO_FILE) << "' created." << endl;
	srand(time(NULL)); // Initialize the random generator.
	char mbstr[30];
	static int fileFIFO =-1;
	cout << "Press <Return> to finish." << endl;
	do {
		std::time_t dateTime = std::time(NULL);
		std::strftime(mbstr, 30, "%F %T", std::localtime(&dateTime));
		if(internalFIFO.size()>=FIFO_SIZE)
			internalFIFO.pop(); // Remove the older message.
		internalFIFO.push( SSTR( "<iec dt='" << mbstr  << "'>"
				<< "<rms ty='v' ph='a'>" << getrandom_avgvar(127.0,2.0) << "</rms>"
				<< "<rms ty='v' ph='b'>" << getrandom_avgvar(125.0,2.0) << "</rms>"
				<< "<rms ty='v' ph='c'>" << getrandom_avgvar(124.0,2.0) << "</rms>"
				<< "<rms ty='c' ph='a'>" << getrandom_avgvar(1.5,2.0) << "</rms>"
				<< "<rms ty='c' ph='b'>" << getrandom_avgvar(1.8,1.0) << "</rms>"
				//<< "<rms ty='c' ph='c'>" << getrandom_avgvar(1.9,1.5) << "</rms>"
				<< "<rms ty='c' ph='c'>" << "</rms>"
				<< "<rms ty='c' ph='n'>" << getrandom_avgvar(2.0,2.0) << "</rms>"

				//<< "<thd ty='v' ph='a'>" << getrandom_minmax(0,.03) << "</thd>"
				<< "<thd ty='v' ph='a'>" << std::scientific << getrandom_minmax(0,.03) << std::fixed <<"</thd>"
				
				<< "<thd ty='v' ph='b'>" << getrandom_minmax(0,.04) << "</thd>"
				<< "<thd ty='v' ph='c'>" << getrandom_minmax(0,.045) << "</thd>"
				<< "<thd ty='c' ph='a'>" << getrandom_minmax(0,.1) << "</thd>"
				<< "<thd ty='c' ph='b'>" << getrandom_minmax(0,.2) << "</thd>"
				<< "<thd ty='c' ph='c'>" << getrandom_minmax(0,.15) << "</thd>"
				<< "<thd ty='c' ph='n'>" << getrandom_minmax(0,.3) << "</thd>"

				<< "<pwr>" << getrandom_avgvar(100.8,1) << "</pwr>"
				//<< "<pwr ph='a'>" << getrandom_avgvar(20.5,4.0) << "</pwr>"
				<< "<pwr ph='a'/>"
				<< "<pwr ph='b'>" << getrandom_avgvar(60.8,8.0) << "</pwr>"
				<< "<pwr ph='c'>" << getrandom_avgvar(50.4,7.8) << "</pwr>"

				<< "<pf>" << getrandom_minmax(0.9,1.0) << "</pf>"
				<< "<pf ph='a'>" << getrandom_minmax(-1.0,-0.9) << "</pf>"
				<< "<pf ph='b'>" << getrandom_minmax(0.9,1.0) << "</pf>"
				<< "<pf ph='c'>" << getrandom_minmax(0.9,1.0) << "</pf>"

				<< "</iec>\n") );
		//cout << internalFIFO.front() << endl;

		//cout << fileFIFO << endl;
		if(fileFIFO < 0) {
			fileFIFO = open(FIFO_FILE, O_WRONLY | O_NONBLOCK | O_CREAT, 0644 );
			if(fileFIFO >= 0)
				cout << "Some process started to hear '" << SSTR(FIFO_FILE) << "'." << endl;
		}
		//cout << fileFIFO << endl;
		if (fileFIFO >= 0) {
			while(!internalFIFO.empty()) {
				write(fileFIFO, internalFIFO.front().c_str(), internalFIFO.front().length());
				internalFIFO.pop();
			}
		}

		usleep(1000000);
	} while(1);
	close(fileFIFO);

	status = remove(FIFO_FILE);
	//printf("%i", status);
	if(status<0)
		cout << "FIFO file '" << SSTR(FIFO_FILE) << "' already deleted." << endl;
	else
		cout << "FIFO file '" << SSTR(FIFO_FILE) << "' deleted." << endl;
	printf("Software IEC61000-4 meter finished.\n");
	return 0;
}

int executeNormal(void) {
	/** Normal execution, evaluate the power/RMS calculations by IEC61000-4 definitions.
	*/
	float gainsV[4], gainsI[4], offsetV[4], offsetI[4];
	dictionary *configurations;
	
	// Check if the file `CONF_FILE` exist (if the board was already calibrated) with don't, call the calibration procedure.
	if( (configurations=iniparser_load(CONF_FILE))==NULL)
		executeCalibrate();
	
	// Read the configuration file `CONF_FILE` with the gains and other definitions.
	printf("Reading configuration file `%s`...\n", CONF_FILE);
	
	
	// Start the PRU software and configure the ADC used.
	printf("Starting the real-time PRU software level...\n");
	
	
	// Start the main loop evaluation the IEC6100-4 power/RMS and other calculations.
	printf("Staring voltage/current signal acquisition...\n");
	while(1){
		// Read the memory values.
		
		
		// Evaluate the RMS, power and other calculations by the IEC6100-4 concept.
		
		// Evaluate the specifics power theories.
		
		// Write the results at the file `FIFO_FILE`.
		
		
	}
	
	
	return 0;
}

int executeCalibrate(void) {
	/** Execute the calibration.
	*/
	dictionary *configurations;
	FILE *configFile;
	
	
	
	printf("Starting configuration procedures...\n");
	if( (configurations=iniparser_load(CONF_FILE))==NULL)
	{
		fprintf(stderr, "`%s` file not reached or not exist. Starting the configuration with a blank profile.\n", CONF_FILE);
	}
	
	
	printf("Enter the name sequence to be used (check the example bellow):\n");
		printf( "ia,va,vc,vb,~,in,ic,ib,~ # Actual board sequency, Channels 4 and 8 are not used.\n");
	channelsUsed = iniparser_getstring(configurations, "channelSequency", "default value");
	cout << channelsUsed;
	
	
	printf("Starting calibration procedure, be sure that calibrated equipment(s) provides voltage and current RMS values.\n");
	
	printf( "Step #1: offset and zero calibration.\n");
		printf("Unconnect the voltage measure wire and the current sensors (transformers) from the circuit, if is used a active sensor unconnect from the circuit but keep them in plugged on the acquisition board.\n");
	
	printf("Step #2: gain calibration.\n");
		printf("Connect the hardware to measure voltage and currents.\n");
		printf("Enter with a valid number or just press <Return> to keep the last configuration.\n");
	
	printf("Calibration made as success, not needed software restart.\n");
	
	
	// Save the the configuration file `CONF_FILE`.
	return 0;
}