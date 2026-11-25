"""lavender touch edge: the home / app-switcher gesture needs edge contacts on a 2340-row panel.

SweetHID.cpp tags contacts that start within SWEET_TOUCH_EDGE_PX of a panel edge with
kIOHIDDigitizerEventFromEdgeTip (UIKit's edge type; no edge bit = no home gesture from an app).
The base checks y > 2399 - 48 for the bottom (its panel is 2400 rows); lavender's NT36672A panel
is 1080x2340, the last row 2339, so no contact was ever a bottom-edge one (seen 2026-11-25: the
lock screen unlocks, an app does not close). Clamp and edge test now use 2339.

usage: python mk_edge.py XNU_TREE
"""
import sys

tree = sys.argv[1]
p = f'{tree}/iokit/Kernel/arm/hid/SweetHID.cpp'
s = open(p, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:60], s.count(old))
    s = s.replace(old, new)


sub('y = y < 0 ? 0 : (y > 2399 ? 2399 : y);',
    'y = y < 0 ? 0 : (y > 2339 ? 2339 : y);         /* lavender panel: 2340 rows */')
sub('y < SWEET_TOUCH_EDGE_PX || y > 2399 - SWEET_TOUCH_EDGE_PX;',
    'y < SWEET_TOUCH_EDGE_PX || y > 2339 - SWEET_TOUCH_EDGE_PX;')
open(p, 'w', newline='\n').write(s)
print('ok')
