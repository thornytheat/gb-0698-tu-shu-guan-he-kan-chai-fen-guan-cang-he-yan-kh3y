# 深度登记 图书馆合刊拆分与馆藏核验

- 规模：中型
- 核心规则：卷期展开使用显式范围语法，合刊只占一册但覆盖多期；增刊独立编号，停刊区间不报缺期
- 年度规则：刊名年中更换时，旧刊与新刊共用同一卷号并归入同一条年度馆藏链；每期保留原刊名，缺口按链核算

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 馆藏接收 | 运行馆藏接收并核对证据 | `POST /api/1` | `app/modules/m1_receive/rules.py` | `tests/test_receive.py` |
| M2 刊名归一 | 运行刊名归一并核对证据 | `POST /api/2` | `app/modules/m2_titles/rules.py` | `tests/test_titles.py` |
| M3 卷期展开 | 运行卷期展开并核对证据 | `POST /api/3` | `app/modules/m3_issues/rules.py` | `tests/test_issues.py` |
| M4 合刊裁决 | 运行合刊裁决并核对证据 | `POST /api/4` | `app/modules/m4_combined/rules.py` | `tests/test_combined.py` |
| M5 缺期定位 | 运行缺期定位并核对证据 | `POST /api/5` | `app/modules/m5_gaps/rules.py`、`app/succession.py` | `tests/test_gaps.py`、`tests/test_succession.py` |
| M6 装订对账 | 运行装订对账并核对证据 | `POST /api/6` | `app/modules/m6_binding/rules.py` | `tests/test_binding.py` |
| M7 补录复核 | 运行补录复核并核对证据 | `POST /api/7` | `app/modules/m7_supplement/rules.py` | `tests/test_supplement.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现会怎样 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | 混合编码 | 静默采信错误值 | 编码回退 | `app/modules/m1_receive/rules.py` | `tests/test_receive.py::test_receive_encoding` |
| TRAP-03 | 引号换行 | 静默采信错误值 | csv逻辑记录 | `app/modules/m1_receive/rules.py` | `tests/test_receive.py::test_receive_multiline` |
| TRAP-05 | 列不齐 | 静默采信错误值 | 隔离 | `app/modules/m1_receive/rules.py` | `tests/test_receive.py::test_receive_badcols` |
| TRAP-08 | 前导零 | 静默采信错误值 | 字符串保形 | `app/modules/m1_receive/rules.py` | `tests/test_receive.py::test_receive_id` |
| TRAP-14 | 装订冲突 | 静默采信错误值 | 列出双侧证据 | `app/modules/m4_combined/rules.py` | `tests/test_combined.py::test_combined_duplicate` |
| TRAP-17 | 刊名演进 | 静默采信错误值 | 别名映射 | `app/modules/m2_titles/rules.py` | `tests/test_titles.py::test_title_alias` |
| TRAP-22 | 多别名 | 静默采信错误值 | 确定代表名 | `app/modules/m2_titles/rules.py` | `tests/test_titles.py::test_title_spaces` |
| TRAP-23 | 停刊区间 | 静默采信错误值 | 缺期集合剔除 | `app/modules/m5_gaps/rules.py` | `tests/test_gaps.py::test_gap_suspended` |
| TRAP-31 | 刊名年中更换 | 只看新刊名漏掉旧刊覆盖，按两个刊名核算重复补录 | 逐期保留原刊名，同卷先后版本并成一条年度链、补录去重 | `app/succession.py` | `tests/test_succession.py::test_succession_old_title_has_gap`、`::test_succession_no_duplicate_supplement` |
| TRAP-32 | 晚到旧刊 | 重算时抹掉已确认年度缺口 | 确认缺口冻结，晚到仅登记，新增缺期另列待复核 | `app/succession.py`、`app/store.py` | `tests/test_succession.py::test_late_old_issue_keeps_confirmed_gap` |
| TRAP-33 | 核验中断 | 从第 1 年重算或跳过未完成年度 | 按年度检查点，从最后连续完成的年度恢复 | `app/modules/m5_gaps/rules.py`、`app/store.py` | `tests/test_succession.py::test_resume_from_last_completed_year` |

## 对账规则

输入记录=采信记录+隔离记录+空行；重复记录归隔离；算法输出另记业务单位，不冒充输入行数。金额/浓度/时长使用Decimal；证据含原始行号。

年度对账：输入行数对账不变；业务侧按年度馆藏链核对确认缺口、逐期原刊名、装订凭据与晚到记录。导出证据 CSV 的`kind`列区分`chain`、`issue`、`late`、`title_conflict`、`binding_conflict`、`result`、`quarantine`。

## 已知不覆盖

不支持超过2MB输入，不执行生产自动放行；异常值需人员复核。不生成采购下单。
