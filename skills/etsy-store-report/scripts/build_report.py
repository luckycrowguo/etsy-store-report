"""Generate a standalone Etsy sales report from a single-store CSV."""
import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from html import escape, unescape
from pathlib import Path
import re


def money(row, key):
    return Decimal(row[key].strip() or "0")


def order_money(rows, key):
    return next((money(row, key) for row in rows if money(row, key)), Decimal(0))


def uk_status(zipcode):
    zip_clean = re.sub(r"[^A-Z0-9]", "", zipcode.upper())
    if zip_clean.startswith("BFPO"):
        return "不可达", "BFPO"
    match = re.fullmatch(r"([A-Z]{1,2})(\d{1,2})[A-Z]?\d[A-Z]{2}", zip_clean)
    if not match:
        return "邮编缺失或格式未识别", ""
    prefix, number = match.group(1), int(match.group(2))
    if prefix in {"IM", "JE", "GY"}:
        return "不可达", prefix
    ranges = {
        "FK": [(18, 21)], "KA": [(27, 28)], "PA": [(20, 49), (60, 78), (80, 80)],
        "TR": [(21, 25)], "AB": [(30, 39), (41, 45), (51, 56)],
        "PH": [(6, 7), (10, 11), (13, 26), (30, 44), (49, 50)],
        "PO": [(30, 41)],
    }
    if prefix in {"IV", "HS", "KW", "ZE", "BT"} or any(
        low <= number <= high for low, high in ranges.get(prefix, [])
    ):
        return "偏远", f"{prefix}{number}"
    return "未命中偏远规则", ""


OPTION_BOUNDARY = re.compile(r"(?:^|,)\s*([^,:]{1,48}):")
PRIVATE_OPTIONS = {"personalization", "personalisation", "name", "photos", "initial", "letter",
                   "message", "notes", "engraving text"}


def options(raw, option_names):
    raw = unescape(raw)
    matches = list(OPTION_BOUNDARY.finditer(raw))
    selected = {}
    for i, match in enumerate(matches):
        key = match[1].strip().lower()
        # Personalization or name can contain commas and apparent option labels.
        if key in PRIVATE_OPTIONS:
            break
        if key in option_names:
            end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
            value = raw[match.end():end].strip()
            if value:
                selected[key] = value
    return selected


class Metrics:
    def __init__(self):
        self.orders = set()
        self.qty = 0
        self.item = Decimal(0)
        self.shipping = Decimal(0)

    @property
    def revenue(self):
        return self.item + self.shipping

    def add(self, oid, qty, item, shipping):
        self.orders.add(oid)
        self.qty += qty
        self.item += item
        self.shipping += shipping


def table(headers, rows, row_details=None):
    header = "".join(f"<th scope='col'>{escape(str(h))}</th>" for h in headers)
    body = "".join("<tr>" + "".join(
        f"<{'th scope=row' if i == 0 else 'td'}>{escape(str(v))}"
        f"{row_details[index] if i == 0 and row_details is not None else ''}</{'th' if i == 0 else 'td'}>"
        for i, v in enumerate(row)) + "</tr>" for index, row in enumerate(rows))
    return f"<div class='table-wrap' tabindex='0'><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>"


def ratio(x, y):
    return x / y if y else 0


def percent(x, y):
    return f"{100 * ratio(x, y):.1f}%"


def ranked(mapping):
    return sorted(mapping.items(), key=lambda pair: (-pair[1].revenue, pair[0]))


def listing_country_bars(listing, order_count, country_products):
    counts = [(country, len(products[listing].orders))
              for country, products in country_products.items()
              if country != "未填写" and listing in products]
    rows = []
    for country, count in sorted(counts, key=lambda pair: (-pair[1], pair[0]))[:3]:
        share = 100 * ratio(count, order_count)
        rows.append(
            f'<div class="country-bar"><div><span>{escape(country)}</span>'
            f'<span>{count:,} 单 · {share:.1f}%</span></div>'
            f'<div class="country-track" aria-hidden="true"><i style="width:{share:.6f}%"></i></div></div>'
        )
    return (
        (f'<small class="listing-id">Listing ID {listing[1]}</small>' if listing[1].isascii() and listing[1].isdigit() else "")
        + '<details class="listing-markets"><summary>购买国家分布</summary>'
        + ("".join(rows) if rows else '<p class="note">暂无收货国家记录。</p>')
        + '</details>'
    )


def bars(daily, fmt, field):
    days = list(daily)
    values = [getattr(m, field) if field != "orders" else len(m.orders) for m in daily.values()]
    maximum = max([1, *values])
    peak = values.index(max(values))
    columns = []
    for day, value in zip(days, values):
        description = escape(f"{day} · {fmt(value)}", quote=True)
        height = max(0, ratio(value, maximum) * 100)
        columns.append(
            f'<button type="button" class="column" aria-label="{description}">'
            f'<i style="height:{height:.3f}%"></i></button>'
        )
    return (
        '<div class="chart-values">'
        f'<p>最高 <strong>{escape(fmt(values[peak]))}</strong> <time>{days[peak]}</time></p>'
        f'<p>查看 <output>{days[-1]} · {escape(fmt(values[-1]))}</output></p></div>'
        '<div class="bars">' + "".join(columns) + '</div>'
    )


def build(source, store, classification):
    categories_by_listing = classification["category_by_listing"]
    option_names = {unescape(name).strip().lower() for name in classification["option_fields"]}
    with source.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("CSV 没有商品明细")
    currencies = {row["Currency"].strip().upper() for row in rows}
    if len(currencies) != 1 or not all(re.fullmatch(r"[A-Z]{3}", code) for code in currencies):
        raise ValueError("此样稿需要单一、已标明的币种")
    currency = currencies.pop()
    fmt = lambda x: f"{'£' if currency == 'GBP' else currency + ' '}{x:,.2f}"
    orders = defaultdict(list)
    transactions = set()
    for row in rows:
        oid, tid = row["Order ID"].strip(), row["Transaction ID"].strip()
        if not oid or not tid or tid in transactions:
            raise ValueError("订单号缺失或交易行重复，请检查源文件")
        orders[oid].append(row)
        transactions.add(tid)

    total = Metrics()
    merchandise = Metrics()
    services = Metrics()
    daily, markets, listings, skus, categories = (defaultdict(Metrics) for _ in range(5))
    country_products = defaultdict(lambda: defaultdict(Metrics))
    listing_titles = {}
    region, remote_prefixes = Counter(), Counter()
    option_qty, combo_qty, combo_orders = defaultdict(Counter), Counter(), defaultdict(set)
    shipping_conflicts = 0
    for oid, items in orders.items():
        first = items[0]
        day = datetime.strptime(first["Date Paid"] or first["Sale Date"], "%m/%d/%Y" if len(
            (first["Date Paid"] or first["Sale Date"]).rsplit("/", 1)[-1]) == 4 else "%m/%d/%y").date().isoformat()
        country = first["Ship Country"].strip() or "未填写"
        qty = [int(row["Quantity"]) for row in items]
        net = [money(row, "Item Total") - money(row, "Discount Amount") for row in items]
        ship = order_money(items, "Order Shipping") - order_money(items, "Shipping Discount")
        shipping_conflicts += any(len({money(r, k) for r in items if money(r, k)}) > 1
                                  for k in ("Order Shipping", "Shipping Discount"))
        for m in (total, daily[day], markets[country]):
            m.add(oid, sum(qty), sum(net), ship)
        weights = [max(n, 0) for n in net]
        weights = weights if sum(weights) else qty
        denom = sum(weights)
        remaining = ship
        is_service = [row["Item Name"].strip().casefold() == "priority production" for row in items]
        if country == "United Kingdom" and not all(is_service):
            status, prefix = uk_status(first["Ship Zipcode"])
            region[status] += 1
            if prefix:
                remote_prefixes[(status, prefix)] += 1
        for i, row in enumerate(items):
            allocated = ship * Decimal(weights[i]) / denom if i < len(items) - 1 else remaining
            remaining -= allocated
            (services if is_service[i] else merchandise).add(oid, qty[i], net[i], allocated)
            title = row["Item Name"].strip().split(",", 1)[0]
            listing_id = row["Listing ID"].strip() or row["Item Name"].strip()
            listing = (listing_titles.setdefault(listing_id, title), listing_id)
            sku = row["SKU"].strip() or "无 SKU"
            category = categories_by_listing.get(listing[1], "未归类")
            for m in (listings[listing], skus[sku], categories[category],
                      country_products[country][listing]):
                m.add(oid, qty[i], net[i], allocated)
            picked = options(row["Variations"], option_names)
            for key, value in picked.items():
                option_qty[key][value] += qty[i]
            if picked:
                combo = " · ".join(f"{k}={v}" for k, v in sorted(picked.items()))
                combo_qty[combo] += qty[i]
                combo_orders[combo].add(oid)

    daily = dict(sorted(daily.items()))
    for group in (daily, markets, listings, skus, categories):
        assert sum(m.qty for m in group.values()) == total.qty
        assert abs(sum(m.revenue for m in group.values()) - total.revenue) < Decimal("0.000001")
    assert total.qty == merchandise.qty + services.qty
    assert sum(region.values()) <= len(markets.get("United Kingdom", Metrics()).orders)
    n = len(total.orders)
    merch_q = merchandise.qty
    cards = [
        ("折后销售额", fmt(total.revenue)), ("订单", f"{n:,} 单"), ("售出数量", f"{total.qty:,} 件"),
        ("客单价", fmt(ratio(total.revenue, n))), ("商品客单价", fmt(ratio(total.item, n))),
        ("运费客单价", fmt(ratio(total.shipping, n))), ("每单件数", f"{ratio(total.qty,n):.2f} 件"),
        ("商品件均价", fmt(ratio(merchandise.item, merch_q))),
        ("含运费件均收入", fmt(ratio(merchandise.revenue, merch_q))),
    ]
    sections = {}
    sections["overview"] = '<div class="kpis">' + "".join(
        f"<div><span>{escape(label)}</span><strong>{escape(value)}</strong></div>" for label, value in cards
    ) + f"</div><p class='note'>折后商品收入 {fmt(total.item)} · 买家净运费收入 {fmt(total.shipping)}</p>"
    trend_charts = (
        ("每日收入", fmt, "revenue"),
        ("每日订单量", lambda x: f"{x:,} 单", "orders"),
        ("每日售出件数", lambda x: f"{x:,} 件", "qty"),
    )
    axis = f'<div class="axis"><span>{min(daily)}</span><span>{max(daily)}</span></div>'
    sections["trend"] = (
        '<div class="split">' + "".join(
            f'<div class="chart"><h3>{title}</h3>{bars(daily, formatter, field)}{axis}</div>'
            for title, formatter, field in trend_charts
        ) + '</div>' +
        '<details class="daily-detail"><summary>查看每日数值</summary>'
        '<p class="note daily-scroll-hint">左右滑动查看更多，日期列会固定在左侧。</p>' + table(
            ["日期", "销售额", "订单", "件数", "件单比（STR）"],
            [(day, fmt(m.revenue), len(m.orders), m.qty,
              f"{m.qty / len(m.orders):.2f}" if m.orders else "—") for day, m in daily.items()],
        ) + "</details>"
    )
    def product_rows(entries):
        return [(label[0] if isinstance(label, tuple) else label, m.qty, len(m.orders), fmt(m.revenue),
                 fmt(ratio(m.item,m.qty))) for label,m in entries]
    product_headers = ["商品","件数","订单","销售额","商品件均价"]
    top_listings = ranked(listings)[:10]
    market_details = [listing_country_bars(key, len(m.orders), country_products)
                      for key, m in top_listings]
    sections["product"] = table(product_headers, product_rows(top_listings), market_details) + (
        "<details><summary>查看 SKU 收入排行 · 前 20</summary>" +
        table(["SKU", *product_headers[1:]], product_rows(ranked(skus)[:20])) + "</details>")
    sections["category"] = table(["品类","订单","件数","销售额","品类客单价"], [
        (label,len(m.orders),m.qty,fmt(m.revenue),fmt(ratio(m.revenue,len(m.orders))))
        for label,m in ranked(categories)])
    sections["country"] = table(["收货国家","订单","订单占比","件数","销售额","收入占比","客单价"], [
        (label,len(m.orders),percent(len(m.orders),n),m.qty,fmt(m.revenue),
         percent(m.revenue,total.revenue),fmt(ratio(m.revenue,len(m.orders))))
        for label,m in ranked(markets)])
    uk_count = sum(region.values())
    sections["remote"] = table(["英国邮编分类","订单","占英国分析订单"], [
        (label,region[label],percent(region[label],uk_count) if uk_count else "—") for label in (
            "偏远","不可达","邮编缺失或格式未识别","未命中偏远规则")])
    if remote_prefixes:
        sections["remote"] += "<details><summary>查看命中的邮编区段</summary>" + table(
            ["分类","邮编区段","订单"], [(status,prefix,count)
             for (status,prefix),count in remote_prefixes.most_common()]) + "</details>"
    sections["country_products"] = "".join(
        f"<details{' open' if i==0 else ''}><summary>{escape(label)} · 前 5</summary>" +
        table(product_headers,product_rows(ranked(country_products[label])[:5])) + "</details>"
        for i,(label,_) in enumerate(ranked(markets)[:5]))
    sections["options"] = "".join(
        f"<details{' open' if i<2 else ''}><summary>{escape(key)} · {sum(freq.values()):,} 件</summary>" +
        table(["选项","件数","同属性占比"], [
            (value, count, percent(count,sum(freq.values()))) for value,count in freq.most_common(12)]) + "</details>"
        for i,(key,freq) in enumerate(sorted(option_qty.items(),key=lambda x:-sum(x[1].values()))[:10]))
    if combo_qty:
        sections["options"] += "<details><summary>查看完整可识别搭配 · 前 30</summary>" + table(
            ["搭配","件数","订单"], [(s,q,len(combo_orders[s])) for s,q in combo_qty.most_common(30)]) + "</details>"
    else:
        sections["options"] = '<p class="note">这份 CSV 没有识别到可统计的结构化选项。</p>'
    leading, leading_m = ranked(markets)[0]
    title, title_m = ranked(listings)[0]
    sections.update(
        store=f"<span>{escape(store)}</span>" if store else "",
        dates=f"{min(daily)} 至 {max(daily)}", last_day=max(daily), currency=currency,
        source=escape(source.name), review=f"{len(rows):,} 行商品明细 · {len(transactions):,} 个唯一交易行",
        highlights=(
            f"<p><strong>{escape(leading)}</strong> 是收入最高的市场，占销售额 "
            f"<strong>{percent(leading_m.revenue,total.revenue)}</strong>。</p>"
            f"<p><strong>{escape(title[0])}</strong> 位居商品链接收入榜首，贡献 "
            f"<strong>{percent(title_m.revenue,total.revenue)}</strong> 的销售额。</p>"
            f"<p>英国偏远邮编命中 <strong>{region['偏远']:,} 单</strong>，"
            f"占英国分析订单 <strong>{percent(region['偏远'],uk_count)}</strong>。</p>"),
        service_note=f"识别到 {len(services.orders)} 单加急生产服务，服务收入 {fmt(services.item)}。",
        conflicts=f"{shipping_conflicts} 单存在不同的非零订单级运费或运费折扣值。",
    )
    return sections


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("csv_file", type=Path)
    cli.add_argument("--store", default="")
    cli.add_argument("--classification", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    classification = json.loads(args.classification.read_text(encoding="utf-8"))
    data = build(args.csv_file, args.store, classification)
    template = Path(__file__).with_name("report-template.html.in").read_text(encoding="utf-8")
    args.output.write_text(re.sub(r"@@(\w+)@@", lambda m: data[m[1]], template), encoding="utf-8")
    print(data["review"], data["dates"], data["currency"], data["conflicts"])
