# 单界面工作台接入说明

## 入口地址

开发环境启动后访问：

```text
http://127.0.0.1:5173/
```

生产环境应由网关或反向代理提供 HTTPS 地址，例如：

```text
https://your-domain.example/community-prediction/
```

指定工程时可附加 `projectId`：

```text
https://your-domain.example/community-prediction/?projectId=9
```

## 上级系统按钮

```html
<button type="button" onclick="window.location.href='/community-prediction/'">
  社区设施预测
</button>
```

新窗口打开：

```html
<button type="button" onclick="window.open('/community-prediction/', '_blank')">
  社区设施预测
</button>
```

内嵌页面：

```html
<iframe
  src="/community-prediction/"
  title="社区设施需求预测"
  style="width:100%;height:100%;min-height:900px;border:0"
></iframe>
```

## 功能范围

单界面工作台包含以下功能：

1. 社区数据：录入、导入、下载社区现状数据。
2. 人口预测：配置人口参数并预测。
3. 设施预测：配置设施标准并预测。
4. 结果报告：查看图表、结果、历史记录并下载报告。
5. 社区管理：查询、查看和维护社区完整信息。
6. 工程管理：新建、切换、备份和恢复工程。

## 可选参数

| 参数 | 作用 |
| --- | --- |
| `projectId` | 进入指定工程 |
| `apiBase` | 指定后端接口地址 |
| `token` | 传入接口访问凭证 |
| `hostOrigin` | 限制宿主页面消息来源 |

生产环境建议把前端与 `/api` 配置为同域 HTTPS 服务。跨域部署时，应同时配置后端 `CORS_ORIGINS`、访问令牌和严格的 `postMessage` 来源校验。不要把 `127.0.0.1` 地址提供给其他设备使用。
