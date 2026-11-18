# 接口

`POST /api/run`：{"text":"CSV内容"}。同规则版本与输入摘要只产生一条批次。

`GET/POST /api/1` 至 `/api/7`：独立样例或自定义文件计算。各模块返回 report、quarantine、balance。

批次结果另含年度馆藏链字段：`chains`（含逐期原刊名与凭据）、`gaps`（缺期定位视图）、`title_conflicts`、`binding_conflicts`、`late`（晚到记录）、`resume`（检查点续算状态）、`blocked`。

`POST /api/review`：id、整数revision、decision取通过或退回。旧版本409；阻断项不能通过。通过时冻结该批次各年度链的已确认缺口。

`GET /api/export/{id}`：唯一证据CSV，`kind`列含 manifest/chain/issue/late/title_conflict/binding_conflict/result/quarantine，可同时核对年度缺口与每期原始刊名。

`GET /health`：存活检查。

错误：结构/数值422，版本冲突409，不存在404，文件过大413。逐行异常进入quarantine。
