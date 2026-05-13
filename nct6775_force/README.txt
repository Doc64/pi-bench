nct6775_force -- minimal helper to make fan readings work on boards where the
in-tree nct6775 driver detects the chip but doesn't bind to it.

WHY THIS EXISTS
On modern Ubuntu kernels (24.04 / 6.x) some motherboards (notably ASUS X99-A II)
ship a Nuvoton NCT6xxx chip that the in-tree driver detects via super-IO scan
("Found NCT6791D or compatible chip at 0x2e:0x290" in dmesg) but never creates
a platform device for. The driver stays loaded with no device to bind to;
no fans, no voltages, no extra temps appear under /sys/class/hwmon.

This module's only job is to register the missing platform device. The in-tree
driver immediately binds to it and the normal hwmon entries appear.

REQUIREMENTS
  - gcc and kernel headers for the running kernel:
      sudo apt install -y build-essential linux-headers-$(uname -r)

BUILD
  make

LOAD (default address 0x290 -- adjust if dmesg shows a different one)
  sudo modprobe nct6775           # if not already loaded
  sudo insmod  nct6775_force.ko   # default addr=0x290
  # OR if the chip lives elsewhere:
  sudo insmod  nct6775_force.ko addr=0x290

VERIFY
  ls /sys/class/hwmon/            # should show one more hwmon device
  sensors                         # fans should now appear

UNLOAD
  sudo rmmod nct6775_force        # safe to do anytime, fans disappear

TROUBLESHOOTING
  - "Invalid module format" -> kernel headers don't match running kernel.
    Reboot after kernel update, then rebuild.
  - dmesg should show "nct6775_force: device registered" + later "nct6775: ..."
    binding messages.
  - If sensors still empty, check dmesg for what nct6775 said when it tried
    to bind; some chips need a different addr.
