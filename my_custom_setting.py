#!/usr/bin/env python3
"""My Custom Setting: battery/charging and touchscreen controls in one window."""
import glob
import os

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Graphene, Gsk, Gtk, Pango

PS = "/sys/class/power_supply"
BAT = f"{PS}/BAT0"
TOUCH_DEV = "i2c-ELAN9008:00"
TOUCH_DRV = "/sys/bus/i2c/drivers/i2c_hid_acpi"
STATES = {
    "Charging": ("Charging", "⚡"),
    "Discharging": ("On battery", "🔋"),
    "Not charging": ("Plugged in, holding charge", "🔌"),
    "Full": ("Full", "🔌"),
}


def read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def read_int(path):
    v = read(path)
    return int(v) if v and v.lstrip("-").isdigit() else None


def charger_port():
    for p in sorted(glob.glob(f"{PS}/ucsi-source-psy-*")):
        cur = read_int(f"{p}/current_now") or 0
        if read(f"{p}/online") == "1" or cur > 0:
            return os.path.basename(p)[-1], cur / 1000
    return None, 0


def touch_enabled():
    return os.path.exists(f"{TOUCH_DRV}/{TOUCH_DEV}")


def fmt_hours(h):
    if h is None or h <= 0 or h > 48:
        return "—"
    return f"{int(h)} h {int(h * 60) % 60:02d} min"


class Row(Adw.ActionRow):
    def __init__(self, title):
        super().__init__(title=title)
        self.value = Gtk.Label(css_classes=["dim-label"])
        self.add_suffix(self.value)

    def set(self, text):
        self.value.set_label(text)


HISTORY_DIR = "/var/lib/upower"
# (label, number of most recent charges to show; None = everything kept)
HISTORY_RANGES = [("Last charge", 1), ("Last 3 charges", 3), ("Last 5 charges", 5),
                  ("Last 10 charges", 10), ("Everything", None)]
COLORS = {"charging": "#33d17a", "discharging": "#ff7800", "other": "#9a9996"}


def load_history(kind):
    """Read upower's (time, value, state) samples for the laptop battery."""
    files = [f for f in glob.glob(f"{HISTORY_DIR}/history-{kind}-*.dat")
             if "generic_id" not in f]
    if not files:
        return []
    points = []
    with open(max(files, key=os.path.getsize)) as f:
        for line in f:
            parts = line.split()
            if len(parts) == 3 and parts[2] != "unknown":
                points.append((int(parts[0]), float(parts[1]), parts[2]))
    return points


def charge_sessions(points):
    """Start times of each run of 'charging' samples."""
    starts, prev = [], None
    for t, _, state in points:
        if state == "charging" and prev != "charging":
            starts.append(t)
        prev = state
    return starts


def range_start(points, count):
    if not points:
        return 0
    starts = charge_sessions(points)
    if count is None or not starts:
        return points[0][0]
    return starts[-min(count, len(starts))]


def fmt_span(hours):
    return f"{hours:.0f} h" if hours < 48 else f"{hours / 24:.1f} days"


class Chart(Gtk.Widget):
    """Line chart coloured by battery state, with a few horizontal grid lines.

    Drawn with GtkSnapshot/GSK so it needs no extra cairo bindings.
    """

    def __init__(self, unit, fixed_max):
        super().__init__(height_request=170, hexpand=True,
                         margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
        self.unit = unit
        self.fixed_max = fixed_max
        self.points = []

    def set_points(self, points):
        self.points = points
        self.queue_draw()

    def text(self, snap, label, x, y, color):
        layout = self.create_pango_layout(label)
        layout.set_font_description(Pango.FontDescription.from_string("Sans 8"))
        tw, th = layout.get_pixel_size()
        snap.save()
        snap.translate(Graphene.Point().init(x, y - th / 2))
        snap.append_layout(layout, color)
        snap.restore()
        return tw

    def stroke(self, snap, builder, color, width):
        snap.append_stroke(builder.to_path(), Gsk.Stroke.new(width), color)

    def do_snapshot(self, snap):
        width, height = self.get_width(), self.get_height()
        fg = self.get_color()
        dim = fg.copy()
        dim.alpha = 0.55
        faint = fg.copy()
        faint.alpha = 0.12
        left, bottom = 34, 20
        w, h = width - left - 6, height - bottom - 8
        if len(self.points) < 2:
            self.text(snap, "Not enough data yet", left, height / 2, dim)
            return

        t0, t1 = self.points[0][0], self.points[-1][0]
        top = self.fixed_max() if self.fixed_max else \
            max(5, max(v for _, v, _ in self.points) * 1.1)

        def x(t):
            return left + (t - t0) / max(1, t1 - t0) * w

        def y(v):
            return 8 + h - min(v, top) / top * h

        grid = Gsk.PathBuilder()
        for i in range(5):
            v = top * i / 4
            grid.move_to(left, y(v))
            grid.line_to(left + w, y(v))
            self.text(snap, f"{v:.0f}", 2, y(v), dim)
        self.stroke(snap, grid, faint, 1)
        for t, align in ((t0, 0), (t1, 1)):
            label = GLib.DateTime.new_from_unix_local(t).format("%a %H:%M")
            layout = self.create_pango_layout(label)
            layout.set_font_description(Pango.FontDescription.from_string("Sans 8"))
            tw = layout.get_pixel_size()[0]
            self.text(snap, label, left + align * (w - tw), height - 9, dim)

        paths = {}
        for (ta, va, sa), (tb, vb, _) in zip(self.points, self.points[1:]):
            b = paths.setdefault(COLORS.get(sa, COLORS["other"]), Gsk.PathBuilder())
            b.move_to(x(ta), y(va))
            # Long gaps mean the laptop was off or asleep: draw them as a step.
            if tb - ta > 1800:
                b.line_to(x(tb), y(va))
            b.line_to(x(tb), y(vb))
        for color, b in paths.items():
            c = Gdk.RGBA()
            c.parse(color)
            self.stroke(snap, b, c, 2)


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="My Custom Setting")
        self.busy = False
        self.set_default_size(440, 680)

        stack = Adw.ViewStack()
        stack.add_titled_with_icon(self.build_power_tab(), "power", "Power",
                                   "battery-full-charging-symbolic")
        stack.add_titled_with_icon(self.build_touch_page(), "touch", "Touchscreen",
                                   "input-tablet-symbolic")

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.ViewSwitcher(stack=stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        view = Adw.ToolbarView(content=stack)
        view.add_top_bar(header)
        self.toasts = Adw.ToastOverlay(child=view)
        self.set_content(self.toasts)

        self.refresh()
        GLib.timeout_add_seconds(2, self.refresh)

    def build_power_tab(self):
        sub = Adw.ViewStack(vexpand=True)
        sub.add_titled(self.build_power_page(), "now", "Now")
        sub.add_titled(self.build_history_page(), "history", "History")
        switcher = Adw.InlineViewSwitcher(stack=sub, halign=Gtk.Align.CENTER,
                                          margin_top=12)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(switcher)
        box.append(sub)
        return box

    def build_history_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                       margin_top=18, margin_bottom=24, margin_start=18, margin_end=18)

        group = Adw.PreferencesGroup()
        self.range_row = Adw.ComboRow(
            title="Show",
            model=Gtk.StringList.new([label for label, _ in HISTORY_RANGES]))
        self.range_row.set_selected(1)
        self.range_row.connect("notify::selected", lambda *_: self.refresh_history())
        self.history_summary = Row("Period")
        group.add(self.range_row)
        group.add(self.history_summary)
        page.append(group)

        self.charge_chart = Chart("Battery (%)", lambda: 100)
        self.rate_chart = Chart("Power (W)", None)
        for title, chart in (("Battery level", self.charge_chart),
                             ("Power", self.rate_chart)):
            g = Adw.PreferencesGroup(title=title)
            g.add(chart)
            page.append(g)

        legend = Gtk.Label(use_markup=True, css_classes=["caption", "dim-label"], label=(
            f"<span foreground='{COLORS['charging']}'>●</span> Charging   "
            f"<span foreground='{COLORS['discharging']}'>●</span> On battery   "
            f"<span foreground='{COLORS['other']}'>●</span> Plugged in, not charging"))
        page.append(legend)
        page.append(Gtk.Label(
            label="From upower's history, which only keeps a few days.",
            css_classes=["caption", "dim-label"], wrap=True))

        self.refresh_history()
        GLib.timeout_add_seconds(60, self.refresh_history)
        return Gtk.ScrolledWindow(child=page, vexpand=True)

    def refresh_history(self):
        charge = load_history("charge")
        rate = load_history("rate")
        _, count = HISTORY_RANGES[self.range_row.get_selected()]
        start = range_start(charge, count)
        charge = [p for p in charge if p[0] >= start]
        rate = [p for p in rate if p[0] >= start]
        self.charge_chart.set_points(charge)
        self.rate_chart.set_points(rate)
        if charge:
            span = (charge[-1][0] - charge[0][0]) / 3600
            sessions = len(charge_sessions(charge))
            since = GLib.DateTime.new_from_unix_local(charge[0][0]).format("%a %H:%M")
            self.history_summary.set(f"since {since} · {fmt_span(span)} · "
                                     f"{sessions} charge{'s' if sessions != 1 else ''}")
        else:
            self.history_summary.set("No data yet")
        return True

    def build_power_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                       margin_top=24, margin_bottom=24, margin_start=18, margin_end=18)

        self.icon = Gtk.Label(css_classes=["title-1"])
        self.percent = Gtk.Label(css_classes=["title-1"])
        self.state = Gtk.Label(css_classes=["title-4", "dim-label"])
        self.bar = Gtk.LevelBar(min_value=0, max_value=100, height_request=14)
        self.bar.add_offset_value("low", 20)
        self.bar.add_offset_value("high", 50)
        self.bar.add_offset_value("full", 100)
        for w in (self.icon, self.percent, self.state, self.bar):
            page.append(w)

        now = Adw.PreferencesGroup(title="Right now")
        self.rate = Row("Power")
        self.time = Row("Time")
        self.port = Row("Charger")
        for r in (self.rate, self.time, self.port):
            now.add(r)
        page.append(now)

        health = Adw.PreferencesGroup(title="Battery")
        self.limit = Row("Charge limit")
        self.health = Row("Health")
        self.cycles = Row("Charge cycles")
        self.energy = Row("Energy")
        for r in (self.limit, self.health, self.cycles, self.energy):
            health.add(r)
        page.append(health)

        charging = Adw.PreferencesGroup(
            title="Charging",
            description="Saved to TLP, kept after reboot. Asks for your password.")
        stop = read_int(f"{BAT}/charge_control_end_threshold") or 80
        self.limit_spin = Adw.SpinRow.new_with_range(50, 100, 5)
        self.limit_spin.set_title("Stop charging at (%)")
        self.limit_spin.set_value(stop)
        charging.add(self.limit_spin)
        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER, margin_top=12)
        save = Gtk.Button(label="Save limit", css_classes=["suggested-action", "pill"])
        save.connect("clicked", self.on_save)
        full = Gtk.Button(label="Charge to 100% once", css_classes=["pill"])
        full.set_tooltip_text("Until the next reboot or the next Save")
        full.connect("clicked", self.on_full_charge)
        buttons.append(save)
        buttons.append(full)
        charging.add(buttons)
        page.append(charging)
        return Gtk.ScrolledWindow(child=page, vexpand=True)

    def build_touch_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                       margin_top=24, margin_bottom=24, margin_start=18, margin_end=18)
        group = Adw.PreferencesGroup(
            title="Touchscreen",
            description="Also turns the stylus off. Back on after a reboot. "
                        "Asks for your password.")
        self.touch_switch = Adw.SwitchRow(title="Touchscreen enabled")
        self.touch_switch.set_active(touch_enabled())
        self.touch_switch.connect("notify::active", self.on_touch_toggled)
        group.add(self.touch_switch)
        page.append(group)
        return Gtk.ScrolledWindow(child=page, vexpand=True)

    def on_touch_toggled(self, row, _pspec):
        want = row.get_active()
        if want == touch_enabled():
            return
        action = "bind" if want else "unbind"
        self.run_root(f"echo {TOUCH_DEV} > {TOUCH_DRV}/{action}",
                      "Touchscreen enabled" if want else "Touchscreen disabled")

    def run_root(self, script, done_msg):
        self.busy = True
        proc = Gio.Subprocess.new(["pkexec", "sh", "-c", script],
                                  Gio.SubprocessFlags.STDERR_SILENCE)

        def finished(p, res):
            try:
                ok = p.wait_check_finish(res)
            except GLib.Error:
                ok = False
            self.busy = False
            self.toasts.add_toast(Adw.Toast(title=done_msg if ok else "Not changed"))
            self.refresh()
        proc.wait_check_async(None, finished)

    def on_save(self, _btn):
        stop = int(self.limit_spin.get_value())
        # This laptop only supports a stop threshold, so START is disabled (0).
        script = (
            "sed -i -E "
            "'s/^#?START_CHARGE_THRESH_BAT0=.*/START_CHARGE_THRESH_BAT0=0/; "
            f"s/^#?STOP_CHARGE_THRESH_BAT0=.*/STOP_CHARGE_THRESH_BAT0={stop}/' "
            "/etc/tlp.conf && tlp setcharge"
        )
        self.run_root(script, f"Charge limit saved: {stop}%")

    def on_full_charge(self, _btn):
        self.run_root("tlp fullcharge", "Charging to 100% until next reboot")

    def refresh(self):
        pct = read_int(f"{BAT}/capacity") or 0
        status = read(f"{BAT}/status", "Unknown")
        power = (read_int(f"{BAT}/power_now") or 0) / 1e6
        now = (read_int(f"{BAT}/energy_now") or 0) / 1e6
        full = (read_int(f"{BAT}/energy_full") or 0) / 1e6
        design = (read_int(f"{BAT}/energy_full_design") or 0) / 1e6
        stop = read_int(f"{BAT}/charge_control_end_threshold") or 100
        port, amps = charger_port()
        plugged = port is not None or read(f"{PS}/AC0/online") == "1"

        label, icon = STATES.get(status, (status, "🔋"))
        if status == "Discharging" and plugged:
            label, icon = "Plugged in, holding charge", "🔌"
        self.icon.set_label(icon)
        self.percent.set_label(f"{pct}%")
        self.state.set_label(label)
        self.bar.set_value(pct)

        if status == "Charging":
            self.rate.set(f"{power:.1f} W into battery")
            target = full * stop / 100
            self.time.set(f"{fmt_hours((target - now) / power if power else None)} to {stop}%")
        elif status == "Discharging" and not plugged:
            self.rate.set(f"{power:.1f} W used")
            self.time.set(f"{fmt_hours(now / power if power else None)} left")
        else:
            self.rate.set("Running from charger")
            self.time.set("—")

        self.port.set(f"USB-C port {port} · up to {amps:.0f} A" if port else "Not connected")
        self.limit.set(f"stops at {stop}%")
        self.health.set(f"{full / design * 100:.0f}%" if design else "—")
        self.cycles.set(read(f"{BAT}/cycle_count", "—"))
        self.energy.set(f"{now:.1f} / {full:.1f} Wh")
        # Keep the switch honest if pkexec was cancelled or it changed elsewhere.
        if not self.busy and self.touch_switch.get_active() != touch_enabled():
            self.touch_switch.set_active(touch_enabled())
        return True


app = Adw.Application(application_id="io.github.keayvan.MyCustomSetting")
app.connect("activate", lambda a: Window(a).present())
app.run()
