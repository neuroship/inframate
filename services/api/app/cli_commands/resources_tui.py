"""Interactive TUI for browsing resources with collapsible tree."""

from collections import defaultdict

from textual.app import App, ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Tree as TreeWidget, Header, Footer, Static, Input
from textual.containers import VerticalScroll
from textual.binding import Binding
from rich.markup import escape as esc
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


# --- Detail modal ---


class ResourceDetailScreen(ModalScreen):
    CSS = """
    ResourceDetailScreen {
        align: center middle;
    }
    #detail-dialog {
        width: 90%;
        max-width: 100;
        height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #detail-content {
        height: 1fr;
    }
    #detail-footer {
        height: 1;
        color: $text-muted;
        text-align: center;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close", priority=True),
        Binding("enter", "dismiss", "Close", priority=True),
        Binding("q", "dismiss", "Close", priority=True),
    ]

    def __init__(self, resource: dict):
        super().__init__()
        self.resource = resource

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="detail-dialog"):
            yield Static(id="detail-content")
            yield Static(id="detail-footer")

    def on_mount(self) -> None:
        r = self.resource
        lines = []

        name = r.get("resource_name", "")
        rtype = r.get("display_type", r.get("resource_type", ""))
        status = r.get("status", "managed")
        action = r.get("action", "no-op")
        status_color = STATUS_COLORS.get(status, "white")
        action_color = ACTION_COLORS.get(action, "dim")

        # Header
        lines.append(f"[bold]{esc(rtype)}: {esc(name)}[/]")
        lines.append("")

        # Status & action
        lines.append(
            f"  [dim]Status:[/]   [{status_color}]{STATUS_LABELS.get(status, status)}[/]"
        )
        lines.append(
            f"  [dim]Action:[/]   [{action_color}]{ACTION_LABELS.get(action, action)}[/]"
        )
        lines.append(f"  [dim]Address:[/]  {esc(r.get('id', ''))}")

        # Presence
        sd = "[blue]Yes[/]" if r.get("in_state") else "[dim]No[/]"
        cd = "[magenta]Yes[/]" if r.get("in_code") else "[dim]No[/]"
        if r.get("in_cloud") is True:
            wd = "[cyan]Yes[/]"
        elif r.get("in_cloud") is False:
            wd = "[dim]No[/]"
        else:
            wd = "[dim]Unknown[/]"
        lines.append(
            f"  [dim]In State:[/] {sd}   [dim]In Code:[/] {cd}   [dim]In Cloud:[/] {wd}"
        )

        # Location
        if r.get("tf_file"):
            loc = r["tf_file"]
            if r.get("tf_line"):
                loc += f":{r['tf_line']}"
            lines.append(f"  [dim]File:[/]    {esc(loc)}")

        # Cloud info
        if r.get("cloud_id"):
            lines.append(f"  [dim]Cloud ID:[/] {esc(r['cloud_id'])}")
        if r.get("arn"):
            lines.append(f"  [dim]ARN:[/]      {esc(r['arn'])}")
        if r.get("console_url"):
            lines.append(f"  [dim]Console:[/]  {esc(r['console_url'])}")

        # Cost
        cost = r.get("cost_monthly")
        if cost and cost > 0:
            lines.append(f"  [dim]Cost:[/]    ${cost:.2f}/mo")

        # Tags
        tags = r.get("tags") or {}
        if tags and isinstance(tags, dict):
            lines.append("")
            lines.append("[bold]Tags[/]")
            for k, v in sorted(tags.items()):
                lines.append(f"  [dim]{esc(str(k))}:[/] {esc(str(v))}")

        # Change details (before/after diff for update/replace)
        before = r.get("before", {}) or {}
        after = r.get("after", {}) or {}

        if action == "create" and after:
            lines.append("")
            lines.append("[bold blue]Will be created with:[/]")
            for k, v in sorted(after.items()):
                if v is not None and k not in ("tags", "tags_all", "timeouts"):
                    lines.append(f"  [blue]+[/] [dim]{k}:[/] {_fmt_val(v)}")

        elif action == "destroy" and before:
            lines.append("")
            lines.append("[bold red]Will be destroyed:[/]")
            for k, v in sorted(before.items()):
                if v is not None and k not in ("tags", "tags_all", "timeouts"):
                    lines.append(f"  [red]-[/] [dim]{k}:[/] {_fmt_val(v)}")

        elif action in ("update", "replace") and before and after:
            lines.append("")
            label = (
                "[bold yellow]Changes:[/]"
                if action == "update"
                else "[bold magenta]Replace (destroy + create):[/]"
            )
            lines.append(label)
            all_keys = sorted(set(list(before.keys()) + list(after.keys())))
            has_diff = False
            for k in all_keys:
                if k in ("tags", "tags_all", "timeouts"):
                    continue
                bv = before.get(k)
                av = after.get(k)
                if bv != av:
                    has_diff = True
                    if bv is None:
                        lines.append(f"  [blue]+[/] [dim]{k}:[/] {_fmt_val(av)}")
                    elif av is None:
                        lines.append(f"  [red]-[/] [dim]{k}:[/] {_fmt_val(bv)}")
                    else:
                        lines.append(
                            f"  [yellow]~[/] [dim]{k}:[/] {_fmt_val(bv)} → {_fmt_val(av)}"
                        )
            if not has_diff:
                lines.append(
                    "  [dim]No attribute changes detected (may be computed)[/]"
                )

        elif action == "no-op":
            # Show current attributes
            attrs = r.get("attributes", {})
            if attrs:
                lines.append("")
                lines.append("[bold]Attributes[/]")
                for k, v in sorted(attrs.items()):
                    if (
                        v is not None
                        and k not in ("tags", "tags_all", "timeouts")
                        and v != ""
                    ):
                        lines.append(f"  [dim]{k}:[/] {_fmt_val(v)}")

        content = self.query_one("#detail-content", Static)
        content.update(Text.from_markup("\n".join(lines)))

        footer = self.query_one("#detail-footer", Static)
        footer.update(Text.from_markup("[dim]Press Escape to close[/]"))


def _fmt_val(v) -> str:
    """Format a value for display, truncating long strings. Output is markup-safe."""
    if isinstance(v, dict):
        if not v:
            return "{}"
        items = [f"{k}={_fmt_val(val)}" for k, val in list(v.items())[:5]]
        s = "{" + ", ".join(items) + "}"
        if len(v) > 5:
            s += f" (+{len(v) - 5} more)"
        return s
    if isinstance(v, list):
        if not v:
            return "\\[]"
        if len(v) <= 3:
            return esc(str(v))
        return esc(f"[{v[0]}, ... +{len(v) - 1} more]")
    s = str(v)
    if len(s) > 80:
        return esc(s[:77] + "...")
    return esc(s)


# --- Main app ---


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
    #search-input {
        display: none;
        height: 1;
        margin: 0 1;
    }
    #search-input.visible {
        display: block;
    }
    #filter-bar {
        height: 1;
        padding: 0 1;
        background: $warning 15%;
        color: $text;
        display: none;
    }
    #filter-bar.active {
        display: block;
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
        # Selection & actions
        Binding("space", "toggle_select", "Select", priority=True),
        Binding("enter", "show_detail", "Detail", priority=True),
        Binding("r", "force_refresh", "Force plan", priority=True),
        Binding("R", "apply", "Apply", priority=True),
        Binding("X", "destroy_selected", "Destroy selected", priority=True),
        # Costs & refresh
        Binding("s", "summarize", "Summarize", priority=True),
        Binding("$", "load_costs", "Costs", priority=True),
        Binding("f5", "refresh", "Refresh", priority=True),
        # Search
        Binding("/", "open_search", "Search", priority=True),
        Binding("escape", "close_search", "Close search", show=False, priority=True),
    ]

    def __init__(
        self,
        rows: list[dict],
        warnings: list[str] | None = None,
        show_costs: bool = False,
        credential_expiry: dict | None = None,
    ):
        super().__init__()
        self.all_rows = rows
        self._warnings = warnings or []
        self.show_costs = show_costs
        self.credential_expiry = credential_expiry
        self.status_filter = "all"
        self.action_filter = "all"
        self.search_query = ""
        self.selected_ids: set[str] = set()
        self._detail_open = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        if self._warnings:
            yield Static(id="warnings")
        yield Static(id="summary")
        yield Static(id="filter-bar")
        yield Static(id="selection-bar")
        yield Input(placeholder="Search resources...", id="search-input", disabled=True)
        yield TreeWidget("Resources", id="tree")
        yield Static(id="legend")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "inframate"
        self._update_subtitle()

        if self._warnings:
            w = self.query_one("#warnings", Static)
            w.update(" │ ".join(self._warnings))

        legend = self.query_one("#legend", Static)
        legend.update(Text.from_markup(
            " [blue]S[/]=State  [magenta]C[/]=Code  [cyan]W[/]=Cloud   "
            "Status: [dim]a[/]ll [dim]m[/]anaged [dim]p[/]ending [dim]d[/]rift [dim]u[/]nmanaged [dim]o[/]rphaned   "
            "Action: [dim]1[/]create [dim]2[/]update [dim]3[/]destroy [dim]4[/]replace [dim]0[/]clear   "
            "[dim]s[/]=summary [dim]/[/]=search [dim]$[/]=costs [dim]F5[/]=refresh [dim]r[/]=force-plan [dim]space[/]=select [dim]enter[/]=detail [dim]R[/]=apply [dim]X[/]=destroy"
        ))

        if self.credential_expiry and self.credential_expiry.get("expires_at"):
            self.set_interval(60, self._update_subtitle)

        self._rebuild()

    def _update_subtitle(self) -> None:
        parts = [f"{len(self.all_rows)} resources"]
        if self.credential_expiry and self.credential_expiry.get("expires_at"):
            from app.services.backend_check import format_time_remaining

            remaining = format_time_remaining(self.credential_expiry["expires_at"])
            if remaining == "expired":
                parts.append("⚠ token expired")
            elif remaining:
                parts.append(f"token: {remaining}")
        self.sub_title = " │ ".join(parts)

    def _filtered_rows(self) -> list[dict]:
        rows = self.all_rows
        if self.status_filter != "all":
            rows = [r for r in rows if r.get("status") == self.status_filter]
        if self.action_filter != "all":
            rows = [r for r in rows if r.get("action") == self.action_filter]
        if self.search_query:
            q = self.search_query.lower()
            rows = [
                r
                for r in rows
                if q in (r.get("resource_name", "") or "").lower()
                or q
                in (r.get("display_type", r.get("resource_type", "")) or "").lower()
                or q in (r.get("service", "") or "").lower()
                or q in (r.get("id", "") or "").lower()
            ]
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
        node.set_label(self._resource_label(node.data))
        self._update_selection_bar()

    def action_destroy_selected(self) -> None:
        selected = [r for r in self.all_rows if r.get("id") in self.selected_ids]
        if not selected:
            self.notify(
                "No resources selected. Use Space to select.", severity="warning"
            )
            return
        self.exit(result=("destroy", selected))

    def action_apply(self) -> None:
        selected = [r for r in self.all_rows if r.get("id") in self.selected_ids]
        if not selected:
            actionable = [
                r
                for r in self.all_rows
                if r.get("action") and r.get("action") != "no-op"
            ]
            if not actionable:
                self.notify("No changes to apply.", severity="warning")
                return
        self.exit(result=("apply", selected))

    def action_show_detail(self) -> None:
        if self._detail_open:
            return
        tree = self.query_one("#tree", TreeWidget)
        node = tree.cursor_node
        if not node:
            return
        if node.data is None:
            node.toggle()
            return
        self._detail_open = True
        self.push_screen(
            ResourceDetailScreen(node.data), callback=self._on_detail_closed
        )

    def _on_detail_closed(self, _result=None) -> None:
        self._detail_open = False

    def action_refresh(self) -> None:
        self.exit(result=("refresh", []))

    def action_force_refresh(self) -> None:
        self.exit(result=("force_refresh", []))

    def action_summarize(self) -> None:
        self.exit(result=("summarize", []))

    def action_load_costs(self) -> None:
        if self.show_costs:
            self.show_costs = False
            self._rebuild()
        else:
            self.exit(result=("load_costs", []))

    def action_open_search(self) -> None:
        search_input = self.query_one("#search-input", Input)
        search_input.disabled = False
        search_input.add_class("visible")
        search_input.focus()

    def action_close_search(self) -> None:
        search_input = self.query_one("#search-input", Input)
        if not search_input.has_class("visible"):
            return
        search_input.remove_class("visible")
        search_input.disabled = True
        search_input.value = ""
        self.search_query = ""
        self._rebuild()
        self.query_one("#tree", TreeWidget).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            self.search_query = event.value
            self._rebuild()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            search_input = self.query_one("#search-input", Input)
            search_input.remove_class("visible")
            search_input.disabled = True
            self.query_one("#tree", TreeWidget).focus()

    def _update_selection_bar(self) -> None:
        bar = self.query_one("#selection-bar", Static)
        n = len(self.selected_ids)
        if n > 0:
            bar.add_class("has-selection")
            bar.update(Text.from_markup(
                f" [bold]{n}[/] selected  —  [bold]R[/]=apply  [bold]X[/]=destroy  [bold]space[/]=toggle"
            ))
        else:
            bar.remove_class("has-selection")

    def _resource_label(self, r: dict) -> Text:
        s = r.get("status", "managed")
        color = STATUS_COLORS.get(s, "white")
        selected = r.get("id") in self.selected_ids

        sd = "[blue]S[/]" if r.get("in_state") else "[dim]·[/]"
        cd = "[magenta]C[/]" if r.get("in_code") else "[dim]·[/]"
        wd = (
            "[cyan]W[/]"
            if r.get("in_cloud")
            else ("[dim]·[/]" if r.get("in_cloud") is not None else "[dim]?[/]")
        )

        name = esc(r.get("resource_name", ""))
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

        cost_str = ""
        if self.show_costs:
            cost = r.get("cost_monthly")
            if cost and cost > 0:
                if cost > 100:
                    cost_str = f" [red bold]${cost:.2f}/mo[/]"
                elif cost > 10:
                    cost_str = f" [yellow]${cost:.2f}/mo[/]"
                else:
                    cost_str = f" [green]${cost:.2f}/mo[/]"

        check = "[bold green]✓[/]" if selected else " "
        return Text.from_markup(
            f"{check} {sd}{cd}{wd} [{color}]●[/] {name}{action_str}{cost_str}"
        )

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

        is_filtered = (
            self.status_filter != "all"
            or self.action_filter != "all"
            or self.search_query
        )
        showing = (
            f"showing {len(rows)}/{len(self.all_rows)}"
            if is_filtered
            else f"{len(self.all_rows)} total"
        )
        if self.search_query:
            showing += f' [dim]search: "{self.search_query}"[/]'

        summary_text = f"{'  '.join(status_parts)}"
        if action_parts:
            summary_text += f"   [dim]│[/]   {'  '.join(action_parts)}"

        # Cost summary
        if self.show_costs:
            filtered_cost = sum(r.get("cost_monthly") or 0 for r in rows)
            if filtered_cost > 0:
                if is_filtered:
                    total_cost = sum(r.get("cost_monthly") or 0 for r in self.all_rows)
                    summary_text += f"   [dim]│[/]   [bold]${filtered_cost:,.2f}[/][dim]/${total_cost:,.2f}/mo[/]"
                else:
                    summary_text += f"   [dim]│[/]   [bold]${filtered_cost:,.2f}/mo[/]"

        summary_text += f"   [dim]{showing}[/]"

        # Filter bar — show active filters clearly
        filter_bar = self.query_one("#filter-bar", Static)
        filter_parts = []
        if self.status_filter != "all":
            color = STATUS_COLORS.get(self.status_filter, "white")
            filter_parts.append(
                f"status: [{color}]{STATUS_LABELS.get(self.status_filter, self.status_filter)}[/]"
            )
        if self.action_filter != "all":
            color = ACTION_COLORS.get(self.action_filter, "white")
            filter_parts.append(
                f"action: [{color}]{ACTION_LABELS.get(self.action_filter, self.action_filter)}[/]"
            )
        if self.search_query:
            filter_parts.append(f'search: [bold]"{self.search_query}"[/]')

        if filter_parts:
            filter_bar.update(
                Text.from_markup(
                    " [bold yellow]Filter:[/]  "
                    + "  [dim]│[/]  ".join(filter_parts)
                    + f"  [dim]({len(rows)}/{len(self.all_rows)})[/]  —  [dim]a[/]=clear status  [dim]0[/]=clear action  [dim]esc[/]=clear search"
                )
            )
            filter_bar.add_class("active")
        else:
            filter_bar.remove_class("active")

        summary = self.query_one("#summary", Static)
        summary.update(Text.from_markup(summary_text))
        self.sub_title = showing

        # Rebuild tree
        tree = self.query_one("#tree", TreeWidget)
        tree.clear()

        groups: dict[str, dict[str, list[dict]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for r in rows:
            svc = r.get("service", "") or "Other"
            rtype = r.get("display_type", r.get("resource_type", "")) or "unknown"
            groups[svc][rtype].append(r)

        sorted_svcs = sorted(
            groups, key=lambda s: sum(len(v) for v in groups[s].values()), reverse=True
        )

        for svc in sorted_svcs:
            types = groups[svc]
            svc_count = sum(len(rs) for rs in types.values())
            svc_cost_str = ""
            if self.show_costs:
                svc_cost = sum(
                    r.get("cost_monthly") or 0 for rs in types.values() for r in rs
                )
                if svc_cost > 0:
                    svc_cost_str = f"  [bold]${svc_cost:,.2f}/mo[/]"
            svc_label = Text.from_markup(
                f"[bold cyan]{svc}[/] [dim]({svc_count})[/]{svc_cost_str}"
            )
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
