"""`symbiont dashboard [view] [--open]`: the address of one dashboard view, on demand.

A down service must not hand out an address that opens a dead page, so the command asks the
service first and says "symbiont offline" instead.
"""

import argparse
import sys

from symbiont.records.dashboard_views import DashboardView, dashboard_address
from symbiont.service.asking import AskService, ServiceAnswerError, ServiceUnavailableError
from symbiont.service.mine_command import MineClient


def show_dashboard(args: argparse.Namespace, ask: AskService, client: MineClient) -> int:
    """Print the address of the chosen view (inbox when none); with `--open`, open it too.

    Exit 0 when the service is down (it prints the offline line, like `status`), 1 when it
    answers unusably. The opener returning False is said aloud; the address is printed anyway.
    """
    try:
        ask("/status", {"project": args.project}, args.port)
    except ServiceUnavailableError as offline:
        sys.stdout.write(f"symbiont offline: {offline}\n")
        return 0
    except ServiceAnswerError as unusable:
        sys.stderr.write(f"symbiont dashboard: {unusable}\n")
        return 1
    view = DashboardView(args.view or DashboardView.INBOX)
    address = dashboard_address(args.port, args.project, view)
    sys.stdout.write(address + "\n")
    if args.open and not client.open_page(address):
        sys.stdout.write("could not open a browser here; open the address above\n")
    return 0
