"""Interactive TUI for browsing resources with collapsible tree."""

from collections import defaultdict

from textual.app import App, ComposeResult
from textual.widgets import Tree as TreeWidget, Header, Footer, Static
from textual.binding import Binding
from rich.text import Text


STATUS_COLORS = {
    "managed": "green",
    "pending": "blue",
    "drift": "yellow",
    "unmanaged": "#ff8c00",
    "orphaned": "red",
}

STATUS_LABELS = {
    "managed": "Managed",
    "pending": "Pending",
    "drift": "Drift",
    "unmanaged": "Unmanaged",
    "orphaned": "Orphaned",
}

ACTION_COLORS = {
    "create": "blue",
    "update": "yellow",
    "destroy": "red",
    "replace": "magenta",
    "no-op": "green",
}

ACTION_LABELS = {
    "create": "Create",
    "update": "Update",
    "destroy": "Destroy",
    "replace": "Replace",
    "no-op": "No change",
}


class ResourcesApp(App):
    CSS = """
    #summary {
        height: auto;
        min-height: 1;
        max-height: 2;
        padding: 0 1;
        background: $surface;
        color: $text-muted;
    }
    #warnings {
        height: auto;
        max-height: 3;
        padding: 0 1;
        color: $warning;
        background: $warning 10%;
    }
    #legend {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        background: $surface;
    }
    #selection-bar {
        height: 1;
        padding: 0 1;
        background: $primary 15%;
        color: $text;
        display: none;
    }
    #selection-bar.has-selection {
        display: block;
    }
    TreeWidget {
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        # Status filters
        Binding("a", "filter_status('all')", "All", priority=True),
        Binding("m", "filter_status('managed')", "Managed", priority=True),
        Binding("p", "filter_status('pending')", "Pending", priority=True),
        Binding("d", "filter_status('drift')", "Drift", priority=True),
        Binding("u", "filter_status('unmanaged')", "Unmanaged", priority=True),
        Binding("o", "filter_status('orphaned')", "Orphaned", priority=True),
        # Action filters
        Binding("1", "filter_action('create')", "Create", priority=True),
        Binding("2", "filter_action('update')", "Update", priority=True),
        Binding("3", "filter_action('destroy')", "Destroy", priority=True),
        Binding("4", "filter_action('replace')", "Replace", priority=True),
        Binding("0", "filter_action('all')", "All actions", priority=True),
        # Tree
        Binding("e", "expand_all", "Expand all"),
        Binding("c", "collapse_all", "Collapse all"),
        # Selection
        Binding("space", "toggle_select", "Select", priority=True),
        Binding("x", "destroy_selected", "Destroy selected", priority=True),
    ]

    def __init__(self, rows: list[dict], warnings: list[str] | None = None):
        super().__init__()
        self.all_rows = rows
        self._warnings = warnings or []
        self.status_filter = "all"
        self.action_filter = "all"
        self.selected_ids: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        if self._warnings:
            yield Static(id="warnings")
        yield Static(id="summary")
        yield Static(id="selection-bar")
        yield TreeWidget("Resources", id="tree")
        yield Static(id="legend")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "inframate resources"
        self.sub_title = f"{len(self.all_rows)} resources"

        if self._warnings:
            w = self.query_one("#warnings", Static)
            w.update(" │ ".join(self._warnings))

        legend = self.query_one("#legend", Static)
        legend.update(Text.from_markup(
            " [blue]S[/]=State  [magenta]C[/]=Code  [cyan]W[/]=Cloud   "
            "Status: [dim]a[/]ll [dim]m[/]anaged [dim]p[/]ending [dim]d[/]rift [dim]u[/]nmanaged [dim]o[/]rphaned   "
            "Action: [dim]1[/]create [dim]2[/]update [dim]3[/]destroy [dim]4[/]replace [dim]0[/]clear   "
            "[dim]space[/]=select [dim]x[/]=destroy"
        ))

        self._rebuild()

    def _filtered_rows(self) -> list[dict]:
        rows = self.all_rows
        if self.status_filter != "all":
            rows = [r for r in rows if r.get("status") == self.status_filter]
        if self.action_filter != "all":
            rows = [r for r in rows if r.get("action") == self.action_filter]
        return rows

    def action_filter_status(self, status: str) -> None:
        self.status_filter = status
        self._rebuild()

    def action_filter_action(self, action: str) -> None:
        self.action_filter = action
        self._rebuild()

    def action_expand_all(self) -> None:
        tree = self.query_one("#tree", TreeWidget)
        tree.root.expand_all()

    def action_collapse_all(self) -> None:
        tree = self.query_one("#tree", TreeWidget)
        for node in tree.root.children:
            node.collapse_all()

    def action_toggle_select(self) -> None:
        tree = self.query_one("#tree", TreeWidget)
        node = tree.cursor_node
        if not node or node.data is None:
            return
        rid = node.data.get("id")
        if not rid:
            return
        if rid in self.selected_ids:
            self.selected_ids.discard(rid)
        else:
            self.selected_ids.add(rid)
        # Update just this node's label
        node.set_label(self._resource_label(node.data))
        self._update_selection_bar()

    def action_destroy_selected(self) -> None:
        selected = [r for r in self.all_rows if r.get("id") in self.selected_ids]
        if not selected:
            self.notify("No resources selected. Use Space to select.", severity="warning")
            return
        self.exit(result=("destroy", selected))

    def _update_selection_bar(self) -> None:
        bar = self.query_one("#selection-bar", Static)
        n = len(self.selected_ids)
        if n > 0:
            bar.add_class("has-selection")
            bar.update(Text.from_markup(
                f" [bold]{n}[/] selected  —  press [bold]x[/] to destroy, [bold]space[/] to toggle"
            ))
        else:
            bar.remove_class("has-selection")

    def _resource_label(self, r: dict) -> Text:
        s = r.get("status", "managed")
        color = STATUS_COLORS.get(s, "white")
        selected = r.get("id") in self.selected_ids

        sd = "[blue]S[/]" if r.get("in_state") else "[dim]·[/]"
        cd = "[magenta]C[/]" if r.get("in_code") else "[dim]·[/]"
        wd = "[cyan]W[/]" if r.get("in_cloud") else ("[dim]·[/]" if r.get("in_cloud") is not None else "[dim]?[/]")

        name = r.get("resource_name", "")
        action = r.get("action", "")
        action_str = ""
        if action and action != "no-op":
            action_map = {
                "create": " [blue]+ create[/]",
                "update": " [yellow]~ update[/]",
                "destroy": " [red]- destroy[/]",
                "replace": " [magenta]± replace[/]",
            }
            action_str = action_map.get(action, f" [dim]{action}[/]")

        check = "[bold green]✓[/]" if selected else " "
        return Text.from_markup(f"{check} {sd}{cd}{wd} [{color}]●[/] {name}{action_str}")

    def _rebuild(self) -> None:
        rows = self._filtered_rows()

        # Status counts (from full set)
        status_counts: dict[str, int] = {}
        for r in self.all_rows:
            s = r.get("status", "managed")
            status_counts[s] = status_counts.get(s, 0) + 1

        # Action counts (from full set)
        action_counts: dict[str, int] = {}
        for r in self.all_rows:
            a = r.get("action", "")
            if a:
                action_counts[a] = action_counts.get(a, 0) + 1

        # Build summary line
        status_parts = []
        for s, color in STATUS_COLORS.items():
            c = status_counts.get(s, 0)
            if c == 0:
                continue
            if self.status_filter == s:
                status_parts.append(f"[bold {color}]▸ {STATUS_LABELS[s]} {c}[/]")
            else:
                status_parts.append(f"[{color}]  {STATUS_LABELS[s]} {c}[/]")

        action_parts = []
        for a, color in ACTION_COLORS.items():
            c = action_counts.get(a, 0)
            if c == 0:
                continue
            if self.action_filter == a:
                action_parts.append(f"[bold {color}]▸ {ACTION_LABELS[a]} {c}[/]")
            else:
                action_parts.append(f"[{color}]  {ACTION_LABELS[a]} {c}[/]")

        showing = f"showing {len(rows)}/{len(self.all_rows)}" if (self.status_filter != "all" or self.action_filter != "all") else f"{len(self.all_rows)} total"

        summary_text = f"{'  '.join(status_parts)}"
        if action_parts:
            summary_text += f"   [dim]│[/]   {'  '.join(action_parts)}"
        summary_text += f"   [dim]{showing}[/]"

        summary = self.query_one("#summary", Static)
        summary.update(Text.from_markup(summary_text))
        self.sub_title = showing

        # Rebuild tree
        tree = self.query_one("#tree", TreeWidget)
        tree.clear()

        groups: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
        for r in rows:
            svc = r.get("service", "") or "Other"
            rtype = r.get("display_type", r.get("resource_type", "")) or "unknown"
            groups[svc][rtype].append(r)

        sorted_svcs = sorted(groups, key=lambda s: sum(len(v) for v in groups[s].values()), reverse=True)

        for svc in sorted_svcs:
            types = groups[svc]
            svc_count = sum(len(rs) for rs in types.values())
            svc_label = Text.from_markup(f"[bold cyan]{svc}[/] [dim]({svc_count})[/]")
            svc_node = tree.root.add(svc_label)

            sorted_types = sorted(types, key=lambda t: len(types[t]), reverse=True)
            for rtype in sorted_types:
                rs = types[rtype]
                type_label = Text.from_markup(f"{rtype} [dim]({len(rs)})[/]")
                type_node = svc_node.add(type_label)

                for r in rs:
                    type_node.add_leaf(self._resource_label(r), data=r)

            svc_node.expand()

        tree.root.expand()
        self._update_selection_bar()
