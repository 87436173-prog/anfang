# 跨境电商销售战报技能

用于 Codex、WorkBuddy 或能读取 SKILL.md 并运行 Python 的助手。读取本技能目录的 SKILL.md，使用 scripts/build_sales_battle_report.py，生成鲜明电商风 PNG。

```text
python -m pip install -r requirements.txt
python scripts/build_sales_battle_report.py --days 1 --downloads "四份导出所在目录" --output "新的交付目录"
```

需要店铺日报、SKU日报、SKU销售统计、仓库库存四份当前导出，以及系统中文字体（Windows 微软雅黑等）。所有业务计算在本地执行。共享库存使用近15天均销；零金额小样不计入销量；4款售完停卖产品保留销售但不预警。详情与SKU名单见 SKILL.md。

WorkBuddy：下载本仓库后只安装 cross-border-sales-battle-report 目录的销售战报技能。自定义包可通过“技能→添加技能→上传技能”导入；如果无法自动注册，直接读取本技能目录的 SKILL.md 并执行脚本。公开技能不需要GitHub令牌。不安装 skills/ 下的其他技能。业务报表和战报图片不属于此技能仓库。
