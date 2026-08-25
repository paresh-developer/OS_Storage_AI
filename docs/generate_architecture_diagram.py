"""Generates docs/architecture.png -- a static PNG version of the Mermaid
architecture diagram in ReadMe.md, using matplotlib (already a core
dependency of this project -- no new install, fully offline).

Run from the repo root: .venv/bin/python docs/generate_architecture_diagram.py
Re-run this after structurally changing the architecture (new module, new
tab, new orchestrator) rather than hand-editing the PNG, and update the
Mermaid block in ReadMe.md to match."""

from __future__ import annotations

import os

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Ellipse

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "architecture.png")

FIG_W, FIG_H = 20, 15
X_MAX, Y_MAX = 196, 132

COL_NODE = "#dbe4f0"
COL_NODE_EDGE = "#33538a"
COL_GROUP = "#f4f6fb"
COL_GROUP_EDGE = "#9aa9c7"
COL_DB = "#e8f0e3"
COL_DB_EDGE = "#4c7a3a"
COL_USER = "#fbe8c8"
COL_USER_EDGE = "#a9722a"
COL_OPTIONAL = "#efefef"
COL_HILITE = "#cfe0ff"


def node(ax, cx, cy, w, h, label, fc=COL_NODE, ec=COL_NODE_EDGE, fontsize=10, dashed=False, weight="normal"):
    box = FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle="round,pad=0,rounding_size=3",
        linewidth=1.4,
        edgecolor=ec,
        facecolor=fc,
        linestyle="dashed" if dashed else "solid",
        zorder=3,
    )
    ax.add_patch(box)
    ax.text(cx, cy, label, ha="center", va="center", fontsize=fontsize, weight=weight, linespacing=1.4, zorder=4)
    return (cx, cy, w, h)


def group(ax, x0, y0, w, h, title):
    box = FancyBboxPatch(
        (x0, y0), w, h,
        boxstyle="round,pad=0,rounding_size=4",
        linewidth=1.6,
        edgecolor=COL_GROUP_EDGE,
        facecolor=COL_GROUP,
        zorder=0,
    )
    ax.add_patch(box)
    ax.text(x0 + w / 2, y0 + h - 5, title, ha="center", va="top", fontsize=12, weight="bold", color="#3a4a6b", zorder=1)
    return (x0, y0, w, h)


def db_cylinder(ax, cx, cy, w, h, label):
    ax.add_patch(Ellipse((cx, cy + h / 2), w, h * 0.35, fc=COL_DB, ec=COL_DB_EDGE, lw=1.4, zorder=2))
    ax.add_patch(plt.Rectangle((cx - w / 2, cy - h / 2), w, h, fc=COL_DB, ec="none", zorder=1))
    ax.plot([cx - w / 2, cx - w / 2], [cy - h / 2, cy + h / 2], color=COL_DB_EDGE, lw=1.4, zorder=2)
    ax.plot([cx + w / 2, cx + w / 2], [cy - h / 2, cy + h / 2], color=COL_DB_EDGE, lw=1.4, zorder=2)
    ax.add_patch(Ellipse((cx, cy - h / 2), w, h * 0.35, fc=COL_DB, ec=COL_DB_EDGE, lw=1.4, zorder=2))
    ax.text(cx, cy, label, ha="center", va="center", fontsize=10, linespacing=1.4, zorder=3)
    return (cx, cy, w, h)


def arrow(ax, a, b, dashed=False, label=None, rad=0.0, color="#4a5a7a", label_frac=0.5, label_dy=0.0):
    (ax_, ay_, aw, ah) = a
    (bx_, by_, bw, bh) = b

    def edge_point(cx, cy, w, h, other_x, other_y):
        dx, dy = other_x - cx, other_y - cy
        if dx == 0 and dy == 0:
            return (cx, cy)
        if abs(dx) / (w / 2 + 1e-9) > abs(dy) / (h / 2 + 1e-9):
            sx = w / 2 if dx > 0 else -w / 2
            sy = sx * dy / dx if dx != 0 else 0
            sy = max(-h / 2, min(h / 2, sy))
        else:
            sy = h / 2 if dy > 0 else -h / 2
            sx = sy * dx / dy if dy != 0 else 0
            sx = max(-w / 2, min(w / 2, sx))
        return (cx + sx, cy + sy)

    start = edge_point(ax_, ay_, aw, ah, bx_, by_)
    end = edge_point(bx_, by_, bw, bh, ax_, ay_)

    patch = FancyArrowPatch(
        start, end,
        arrowstyle="-|>",
        mutation_scale=13,
        linewidth=1.3,
        color=color,
        linestyle="dashed" if dashed else "solid",
        connectionstyle=f"arc3,rad={rad}",
        zorder=5,
    )
    ax.add_patch(patch)
    if label:
        mx = start[0] + (end[0] - start[0]) * label_frac
        my = start[1] + (end[1] - start[1]) * label_frac + label_dy
        ax.text(mx, my, label, ha="center", va="center", fontsize=8.2, style="italic", color="#444",
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="#ccc", alpha=0.95), zorder=6)


def main():
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    ax.set_xlim(0, X_MAX)
    ax.set_ylim(-32, Y_MAX)
    ax.axis("off")
    ax.set_aspect("equal")

    # --- User + GUI row ---
    user = node(ax, 98, 126, 26, 8, "User", fc=COL_USER, ec=COL_USER_EDGE, fontsize=12, weight="bold")

    gui_group = group(ax, 4, 104, 188, 18, "storage_ai/gui/   (PySide6 desktop UI)")
    chart_tabs = node(ax, 22, 108.5, 30, 8, "Dashboard · File Types\nForecast · Folders · Clusters", fontsize=8.6)
    list_tabs = node(ax, 55, 108.5, 26, 8, "Duplicates · Unused\nFiles · Recommendations", fontsize=8.6)
    app_tab = node(ax, 105, 108.5, 40, 8, "App Data Suggestions")
    live_tab = node(ax, 165, 108.5, 34, 8, "Live Activity")

    arrow(ax, user, chart_tabs, rad=-0.05)
    arrow(ax, user, list_tabs, rad=-0.03)
    arrow(ax, user, app_tab)
    arrow(ax, user, live_tab, rad=0.05)

    # --- Three side-by-side columns ---
    CORE_X, DISC_X, MON_X = 4, 68, 132
    COL_W = 60
    COL_Y, COL_H = -14, 112

    core_group = group(ax, CORE_X, COL_Y, COL_W, COL_H, "pipeline.py -- run_analysis\n(one folder)")
    disc_group = group(ax, DISC_X, COL_Y, COL_W, COL_H, "Application discovery\n(docs Section 8)")
    mon_group = group(ax, MON_X, COL_Y, COL_W, COL_H, "Live activity monitoring\n(docs Section 6)")

    # Core pipeline
    cl_x, cr_x = CORE_X + 16, CORE_X + 44
    scanner = node(ax, cl_x, 78, 26, 8, "scanner.py")
    classify = node(ax, cr_x, 78, 26, 8, "path_classifier.py")
    hashing = node(ax, cl_x, 60, 30, 8, "hashing.py →\nduplicates.py")
    advisor = node(ax, cr_x, 60, 26, 8, "category_advisor.py")
    unused = node(ax, cl_x, 42, 26, 8, "unused.py")
    rec = node(ax, cr_x, 34, 26, 10, "recommender.py", fc=COL_HILITE)
    cluster = node(ax, cl_x, 24, 26, 8, "clustering.py")
    actions = node(ax, cr_x, 14, 26, 10, "actions.py\n(trash / archive)", fc=COL_HILITE)
    predict = node(ax, cl_x, 6, 26, 8, "prediction.py")

    arrow(ax, scanner, classify)
    arrow(ax, scanner, hashing)
    arrow(ax, scanner, unused)
    arrow(ax, scanner, cluster, rad=-0.28)
    arrow(ax, scanner, predict, rad=-0.4)
    arrow(ax, classify, advisor)
    arrow(ax, hashing, rec, rad=0.12)
    arrow(ax, unused, rec, rad=-0.1)
    arrow(ax, predict, rec, rad=0.35)
    arrow(ax, advisor, rec)
    arrow(ax, rec, actions)

    arrow(ax, chart_tabs, scanner, rad=0.12)
    arrow(ax, list_tabs, scanner, rad=0.22)

    # Application discovery
    dl_x, dr_x = DISC_X + 16, DISC_X + 44
    app_sugg = node(ax, dl_x, 78, 28, 9, "app_suggestions.py\n(every running process)", fontsize=8.8)
    app_disc = node(ax, dr_x, 78, 24, 9, "app_discovery.py")
    tier1 = node(ax, dl_x, 56, 30, 9, "1. process_introspection.py\n(live /proc observation)", fontsize=8.4)
    tier2 = node(ax, dl_x, 34, 30, 9, "2. config_discovery.py\n(JSON / YAML / TOML / INI)", fontsize=8.4)
    tier3 = node(ax, dr_x, 34, 26, 9, "3. llm_config_extractor.py\n(optional, CPU-only)", fc=COL_OPTIONAL, dashed=True, fontsize=8.4)

    arrow(ax, app_sugg, app_disc)
    arrow(ax, app_disc, tier1, rad=0.12)
    arrow(ax, app_disc, tier2, rad=0.28)
    arrow(ax, app_disc, tier3, dashed=True, label="only if 1 & 2\nfound nothing", label_frac=0.5, label_dy=0)
    arrow(ax, app_tab, app_sugg, rad=0.1)

    # cross-column: discovery findings classify/advise using Core's own modules
    arrow(ax, app_disc, classify, rad=-0.22, color="#7a8bb0")
    arrow(ax, app_disc, advisor, rad=-0.12, color="#7a8bb0")

    # Live activity monitoring
    ml_x, mr_x = MON_X + 16, MON_X + 44
    svc = node(ax, ml_x, 74, 28, 9, "watcher_service.py\n(standalone process)", fontsize=8.8)
    watch = node(ax, mr_x, 74, 24, 9, "watcher.py\n(watchdog)")
    audit = node(ax, ml_x, 40, 28, 9, "audit_log.py\n(Linux auditd, optional)", fc=COL_OPTIONAL, dashed=True, fontsize=8.6)
    trend = node(ax, mr_x, 40, 24, 9, "trend_detector.py")

    arrow(ax, svc, watch)
    arrow(ax, svc, audit, dashed=True, label="--enable-audit", label_frac=0.5, label_dy=2.5)
    arrow(ax, watch, trend)
    arrow(ax, live_tab, watch, rad=-0.1)

    # --- Shared persistence ---
    db = db_cylinder(ax, 98, -23, 50, 13, "database.py\nSQLite -- ~/.storage_ai/")
    arrow(ax, rec, db, rad=0.15)
    arrow(ax, watch, db, rad=-0.15)
    arrow(ax, trend, db, rad=-0.05)

    fig.tight_layout(pad=0.6)
    fig.savefig(OUTPUT_PATH, dpi=170, facecolor="white")


if __name__ == "__main__":
    main()
