from __future__ import annotations

from typing import Any

from src.config.logging import get_logger
from src.models.agents import AggregationResult, PresentationData, SearchResult

logger = get_logger(module="presentation_agent")


def build_presentation(
    search_result: SearchResult | None = None,
    aggregation: AggregationResult | None = None,
    page: int = 1,
    page_size: int = 50,
    total_pages: int = 1,
) -> PresentationData:
    """Build presentation artifacts: Bootstrap 5 table HTML + Chart.js configs."""

    table_html = ""
    chart_configs: list[dict[str, Any]] = []
    stats_cards: list[dict[str, str]] = []

    if search_result and search_result.emails:
        table_html = _render_email_table(search_result, page, page_size, total_pages)
        stats_cards.append({"label": "Total Results", "value": str(search_result.total_count)})
        stats_cards.append({"label": "Query Time", "value": f"{search_result.query_time_ms:.0f}ms"})

    if aggregation:
        if aggregation.chart_type:
            chart_configs.append(_build_chart_config(aggregation))
        if aggregation.summary:
            for key, val in aggregation.summary.items():
                stats_cards.append({"label": key.replace("_", " ").title(), "value": str(val)})
        if aggregation.data and not search_result:
            table_html = _render_aggregation_table(aggregation)

    return PresentationData(
        table_html=table_html,
        chart_configs=chart_configs,
        stats_cards=stats_cards,
        export_available=bool(search_result and search_result.total_count > 0),
    )


def _render_email_table(result: SearchResult, page: int, page_size: int, total_pages: int) -> str:
    rows_html = ""
    for email in result.emails:
        date = str(email.get("date_utc", ""))[:16]
        from_addr = _escape(str(email.get("from_address", "")))
        from_name = _escape(str(email.get("from_name", "")))
        sender = f"{from_name} &lt;{from_addr}&gt;" if from_name else from_addr
        to = _escape(str(email.get("to_addresses", "")))
        subject = _escape(str(email.get("subject", "")))
        attach = "Yes" if email.get("has_attachments") else ""
        attach_count = email.get("attachment_count", 0)
        size_kb = round(email.get("size_bytes", 0) / 1024, 1)
        msg_id = email.get("message_id", "")
        thread_id = email.get("thread_id", "")
        snippet = _escape(str(email.get("snippet", ""))[:100])

        rows_html += f"""
        <tr>
            <td class="text-nowrap">{date}</td>
            <td title="{from_addr}">{sender}</td>
            <td>{to[:60]}</td>
            <td><a href="#" class="email-link" data-message-id="{_escape(msg_id)}"
                   title="{snippet}">{subject[:80]}</a></td>
            <td class="text-center">{f"{attach} ({attach_count})" if attach else "-"}</td>
            <td class="text-end">{size_kb} KB</td>
            <td>
                <a href="#" class="btn btn-sm btn-outline-primary view-email" data-message-id="{_escape(msg_id)}">View</a>
                {f'<a href="#" class="btn btn-sm btn-outline-secondary view-thread" data-thread-id="{_escape(thread_id)}">Thread</a>' if thread_id else ""}
            </td>
        </tr>"""

    pagination_html = _render_pagination(page, total_pages)

    return f"""
    <div class="table-responsive">
        <table class="table table-striped table-hover" id="emailTable">
            <thead class="table-dark">
                <tr>
                    <th data-sortable="true">Date</th>
                    <th data-sortable="true">From</th>
                    <th>To</th>
                    <th data-sortable="true">Subject</th>
                    <th data-sortable="true">Attachments</th>
                    <th data-sortable="true">Size</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    </div>
    <div class="d-flex justify-content-between align-items-center mt-3">
        <span class="text-muted">Showing {len(result.emails)} of {result.total_count} emails</span>
        {pagination_html}
    </div>"""


def _render_pagination(page: int, total_pages: int) -> str:
    if total_pages <= 1:
        return ""
    items = ""
    items += f'<li class="page-item {"disabled" if page <= 1 else ""}"><a class="page-link" href="#" data-page="{page - 1}">Previous</a></li>'

    start = max(1, page - 3)
    end = min(total_pages, page + 3)
    if start > 1:
        items += '<li class="page-item"><a class="page-link" href="#" data-page="1">1</a></li>'
        if start > 2:
            items += '<li class="page-item disabled"><span class="page-link">...</span></li>'

    for p in range(start, end + 1):
        active = "active" if p == page else ""
        items += f'<li class="page-item {active}"><a class="page-link" href="#" data-page="{p}">{p}</a></li>'

    if end < total_pages:
        if end < total_pages - 1:
            items += '<li class="page-item disabled"><span class="page-link">...</span></li>'
        items += f'<li class="page-item"><a class="page-link" href="#" data-page="{total_pages}">{total_pages}</a></li>'

    items += f'<li class="page-item {"disabled" if page >= total_pages else ""}"><a class="page-link" href="#" data-page="{page + 1}">Next</a></li>'

    return f'<nav><ul class="pagination mb-0">{items}</ul></nav>'


def _render_aggregation_table(agg: AggregationResult) -> str:
    if not agg.data:
        return ""
    columns = list(agg.data[0].keys())
    headers = "".join(f'<th data-sortable="true">{_escape(c.replace("_", " ").title())}</th>' for c in columns)
    rows = ""
    for row in agg.data:
        cells = "".join(f"<td>{_escape(str(row.get(c, '')))}</td>" for c in columns)
        rows += f"<tr>{cells}</tr>"

    return f"""
    <div class="table-responsive">
        <table class="table table-striped table-hover" id="aggregationTable">
            <thead class="table-dark"><tr>{headers}</tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>"""


def _build_chart_config(agg: AggregationResult) -> dict[str, Any]:
    colors = [
        "#0d6efd",
        "#6610f2",
        "#6f42c1",
        "#d63384",
        "#dc3545",
        "#fd7e14",
        "#ffc107",
        "#198754",
        "#20c997",
        "#0dcaf0",
        "#6c757d",
        "#adb5bd",
        "#495057",
        "#343a40",
        "#212529",
    ]

    dataset: dict[str, Any] = {
        "label": agg.title,
        "data": agg.values,
    }

    if agg.chart_type in ("pie", "doughnut"):
        dataset["backgroundColor"] = colors[: len(agg.values)]
    else:
        dataset["backgroundColor"] = colors[0]
        dataset["borderColor"] = colors[0]
        if agg.chart_type == "line":
            dataset["fill"] = False
            dataset["tension"] = 0.3

    return {
        "type": agg.chart_type,
        "data": {
            "labels": agg.labels,
            "datasets": [dataset],
        },
        "options": {
            "responsive": True,
            "plugins": {
                "title": {"display": True, "text": agg.title},
                "legend": {"display": agg.chart_type in ("pie", "doughnut")},
            },
        },
    }


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
