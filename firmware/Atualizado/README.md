# EdgeMeter
How to configure BBB for the first time?

1 - Flash old version of Jessie 3.8.13-bone70
http://exploringbeaglebone.com/chapter2/

2 - run:
apt-get remove wicd-gtk wicd-curses wicd-cli wicd-daemon python-wicd
apt-get autoremove
apt-get install debian-keyring debian-archive-keyring

3 - Edit:
sudo nano /etc/apt/sources.list
Change:
deb [arch=armhf] http://debian.beagleboard.org/packages wheezy-bbb main
#deb-src [arch=armhf] http://debian.beagleboard.org/packages wheezy-bbb main
To:
#deb [arch=armhf] http://debian.beagleboard.org/packages wheezy-bbb main
#deb-src [arch=armhf] http://debian.beagleboard.org/packages wheezy-bbb main

4 - Update:
apt-get update
apt-get upgrade

5 - Set Network as wished:
cd /etc/network
sudo nano interfaces

6 - Set PATH, PINS and encoding:
nano ~/.profile
add to the file:
export SLOTS=/sys/devices/bone_capemgr.9/slots
export PINS=/sys/kernel/debug/pinctrl/44e10800.pinmux/pins
export LC_ALL="en_US.UTF-8"

7 - Enter visudo and add below lines after "Defaults env_reset":
visudo
Add after "Defaults env_reset":
Defaults env_keep += "SLOTS"
Defaults env_keep += "PINS"

8 - Configure system data/locale, not time and date:
dpkg-reconfigure tzdata

9 - Clone our git:
git clone https://gitlab.unicamp.br/joelunic/edgemeter
go to the program folder and run the ./build-ADS8688

10 - Disable HDMI:
nano /boot/uboot/uEnv.txt
Uncomment the disable HDMI line:
cape_disable=capemgr.disable_partno=BB-BONELT-HDMI,BB-BONELT-HDMIN

11 - Copy DTO to firmware folder:
cp EBB-PRU-ADC-00A0.dtbo /lib/firmware/

12 - Start DTO on boot:
add "CAPE=PRU-ADC-ADS8688" to:
nano /etc/default/capemgr
add "cape_enable=capemgr.enable_partno=PRU-ADC-ADS8688" below "example" to:
nano /boot/uboot/uEnv.txt

13 - reboot and allocate memory:
reboot
rmmod uio_pruss
modprobe uio_pruss extram_pool_sz=0x1E8480

14 - Go to program folder and run the program