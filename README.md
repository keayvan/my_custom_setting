# My Custom Setting

A small GTK4 / libadwaita settings window for Ubuntu with two tabs:
**Power** (battery status and charge limit) and **Touchscreen** (on/off).

Built for an ASUS Zenbook S16 (UM5606GA), GNOME 50, with [TLP](https://linrunner.de/tlp/).

## Power tab

Refreshed every 2 seconds:

- Battery percentage and state (charging, on battery, plugged in and holding)
- Power going into the battery, or being used from it
- Time left on battery, or time until the charge limit
- Which USB-C port the charger is on
- Charge limit, battery health, charge cycles and stored energy

Charging controls:

- **Stop charging at** + **Save limit** writes `STOP_CHARGE_THRESH_BAT0` to
  `/etc/tlp.conf` and applies it, so it survives a reboot.
- **Charge to 100% once** runs `tlp fullcharge`: the battery charges fully until the
  next reboot or the next Save.

### History

A **History** sub-tab inside Power draws battery level and power over time,
coloured by state (charging, on battery, plugged in). Pick how far back to look:
the last 1, 3, 5 or 10 charges, or everything. The data comes from upower's own
history in `/var/lib/upower`, which only keeps a few days.

## Touchscreen tab

A switch that unbinds the touchscreen from the `i2c_hid_acpi` driver to turn it off,
and binds it again to turn it on. The stylus uses the same hardware, so it goes off
too. After a reboot the touchscreen is always on again.

For another laptop, find your touchscreen with
`ls /sys/bus/i2c/drivers/i2c_hid_acpi/` and change `TOUCH_DEV` at the top of
`my_custom_setting.py`. Don't pick your touchpad.

Every change asks for your password through `pkexec`.

## Requirements

```bash
sudo apt install tlp python3-gi gir1.2-adw-1
```

Your laptop must expose `/sys/class/power_supply/BAT0/charge_control_end_threshold`.

## Install

```bash
git clone https://github.com/keayvan/my_custom_setting.git ~/my_custom_setting
~/my_custom_setting/install.sh
```

Then search for **My Custom Setting** in the app menu.

## Uninstall

```bash
~/my_custom_setting/uninstall.sh
rm -rf ~/my_custom_setting
```
