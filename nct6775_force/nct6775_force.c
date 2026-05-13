/*
 * nct6775_force.c -- create a platform device so nct6775 will bind to it.
 *
 * Some boards (e.g. ASUS X99-A II) have an NCT chip that the in-tree
 * super-IO scanner sees ("Found NCT6791D or compatible chip at 0x2e:0x290"
 * in dmesg) but doesn't actually create a platform device for, leaving
 * the in-tree nct6775 driver loaded with nothing to bind to and no
 * fans visible under /sys/class/hwmon.
 *
 * This module exists for one purpose: register a platform device named
 * "nct6775" claiming the I/O port range the chip lives at, so the in-tree
 * driver auto-binds to it. Then fan*_input, temp*_input, in*_input all
 * appear as a normal hwmon device.
 *
 * Usage:
 *     sudo insmod nct6775_force.ko             # uses default 0x290
 *     sudo insmod nct6775_force.ko addr=0x290  # explicit address
 *     ls /sys/class/hwmon/                     # new hwmon should appear
 *     sensors                                  # fans should now show
 *
 * Unload:
 *     sudo rmmod nct6775_force
 */

#include <linux/module.h>
#include <linux/init.h>
#include <linux/platform_device.h>
#include <linux/ioport.h>

static unsigned short addr = 0x290;
module_param(addr, ushort, 0444);
MODULE_PARM_DESC(addr, "I/O port base address of the NCT chip (default 0x290)");

static struct platform_device *pdev;

static int __init nct6775_force_init(void)
{
    struct resource res = {
        .name  = "nct6775_force",
        .start = addr,
        .end   = addr + 7,
        .flags = IORESOURCE_IO,
    };

    pr_info("nct6775_force: registering platform device 'nct6775' at I/O 0x%x\n", addr);

    pdev = platform_device_register_simple("nct6775", -1, &res, 1);
    if (IS_ERR(pdev)) {
        long err = PTR_ERR(pdev);
        pr_err("nct6775_force: platform_device_register_simple failed: %ld\n", err);
        return err;
    }

    pr_info("nct6775_force: device registered; nct6775 driver should bind shortly\n");
    return 0;
}

static void __exit nct6775_force_exit(void)
{
    platform_device_unregister(pdev);
    pr_info("nct6775_force: platform device unregistered\n");
}

module_init(nct6775_force_init);
module_exit(nct6775_force_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("pi_bench setup helper");
MODULE_DESCRIPTION("Register a platform device so the in-tree nct6775 driver can bind");
MODULE_VERSION("0.1");
