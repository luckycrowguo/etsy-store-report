# Etsy 店铺销售报告 Skill

将一家 Etsy 店铺的 `EtsySoldOrderItems` CSV 生成中文 HTML 销售报告。报告可在浏览器离线打开，包含每日趋势、件单比（STR）、商品排行、品类客单价、国家和偏远邮编分析、下单选项分布。

## 首次使用

本仓库公开可读。首次使用时，在 Codex 发送：

> `$skill-installer` 请安装这个 Skill：https://github.com/luckycrowguo/etsy-store-report/tree/main/skills/etsy-store-report

## 生成报告

把自己的 Etsy 订单 CSV 附到 Codex，再发送：

> `$etsy-store-report` 请用附件里的 CSV 生成 HTML 店铺销售报告。

报告的日期范围和币种来自 CSV。店铺名可省略。Codex 会根据本次文件识别品类和下单选项。

打开 Codex 返回的 HTML 文件即可阅读。真实订单和生成的销售报告保存在自己的工作环境，仓库用于分发 Skill。
