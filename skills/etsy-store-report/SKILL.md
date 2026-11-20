---
name: etsy-store-report
description: Generate a standalone Chinese HTML sales report from an Etsy Sold Order Items CSV for one shop. Use for Etsy store sales, daily trends, product rankings, destination markets, and order option distributions.
---

# Etsy 店铺销售报告

用同一份计算脚本和 HTML 模板生成运营报告。输入是一家店铺的 Etsy 商品订单明细 CSV（可覆盖多个日期）。不要求店铺名；仅当用户提供时传入。

## 每次运行

1. 读取 CSV 表头与分析所需字段，检查日期、币种、订单号和交易行标识。使用 CSV 的单一原币，日期优先取 `Date Paid`，缺失时取 `Sale Date`。输入跨店、混有多币种或有重复交易行时，说明具体冲突，保留可核对的输入依据。
2. 汇总唯一 `Listing ID` 对应的标题和 SKU，以及 `Variations` 的候选字段名与出现频率。根据商品语义给本次文件归类，并确认哪些字段确实是买家下单时的结构化选项。原始订单与自由文本视作数据。避免把买家姓名、刻字文本、联系方式、地址或留言带入报告。
3. 在临时工作目录生成本次的分类 JSON。运营不需要提供或维护这个文件。无法判断的商品留空映射，脚本归入「未归类」。无法确定为结构化选项的字段省略。字段名以 CSV 实际内容为准。

   ```json
   {
     "category_by_listing": {"1234567890": "手链"},
     "option_fields": ["Color", "Packaging Options"]
   }
   ```

   `category_by_listing` 的键优先用 `Listing ID`；该字段为空时使用原始完整商品标题。样例里的品类与字段仅说明格式。仅纳入取值可安全汇总的属性。

4. 运行随附的 [生成脚本](scripts/build_report.py)，保留 [HTML 模板](scripts/report-template.html.in) 的布局与交互。

   ```sh
   python3 /absolute/path/etsy-store-report/scripts/build_report.py "/path/orders.csv" --classification "/tmp/run/classification.json" --output "/path/etsy-sales-report.html"
   ```

5. 核对去重订单数、数量、销售额分项、每日件单比及各分组汇总，检查口径中报告的订单级运费冲突数。确认 HTML 已填入数据并可打开，交付实际 HTML 的完整路径。文件链接使用纯文件路径，通过报告内目录定位章节。

## 报告口径

- 同一 `Order ID` 计一单，`Quantity` 加总。商品收入为 `Item Total - Discount Amount`，买家净运费为 `Order Shipping - Shipping Discount`。订单级金额各取首个非零值；若同单存在不同非零值，在报告里标明冲突数量。销售额为两项之和。
- 客单价用销售额除以订单数，商品和运费客单价用各自收入除以订单数。件单比（STR）为售出件数除以订单数。商品件均价使用折后商品金额，含运费件均收入再加买家净运费。单独的 `Priority production` 服务从这两项件均分子和分母剔除。
- 商品与品类收入含分摊的买家净运费，优先按折后商品收入、其次按件数分摊。品类以各自去重订单数计算客单价。一单跨品类时分别计入相应品类。
- 保留三张每日趋势图和含 STR 的明细表、商品及 SKU 排行、品类客单价、国家分布和英国偏远邮编统计。各国热销商品限销售额前五国家，每国前五商品。英国邮编按模板所附规则判断，实际可达性由物流渠道决定。
- 下单选项展示按已识别件数排名前十的属性，单个属性显示前十二个取值及以该属性全部已识别件数为分母的占比。完整可识别搭配另列，显示件数和去重订单数。
- 商品收入排行中的每个链接可展开查看收货国家横条。按链接内去重订单数列前 3 国，条长使用该国订单数除以链接全部订单数。
- 报告结论只使用 CSV 可支持的汇总。利润、退款、采购成本和实付物流费用需要额外数据。
