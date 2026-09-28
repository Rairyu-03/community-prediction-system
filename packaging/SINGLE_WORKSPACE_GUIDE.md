# 单界面工作台接入说明

## 入口地址

打包程序启动后，默认地址已经直接进入精简单界面：

```text
http://127.0.0.1:8765
```

以下兼容地址具有相同效果：

```text
http://127.0.0.1:8765/workspace
```

指定工程：

```text
http://127.0.0.1:8765/workspace?projectId=9
```

开发环境也可使用：

```text
http://127.0.0.1:5173/?workspace=1
```

## 上级系统按钮

```html
<button type="button" onclick="window.location.href='http://127.0.0.1:8765/workspace'">
  社区设施预测
</button>
```

新窗口打开：

```html
<button type="button" onclick="window.open('http://127.0.0.1:8765/workspace', '_blank')">
  社区设施预测
</button>
```

内嵌页面：

```html
<iframe
  src="http://127.0.0.1:8765/workspace"
  title="社区设施需求预测"
  style="width:100%;height:100%;min-height:900px;border:0"
></iframe>
```

## 功能范围

单界面工作台仅改变布局，不改变业务功能和数据：

1. 社区数据：录入、导入、下载社区现状数据。
2. 人口预测：配置人口参数并预测。
3. 设施预测：配置设施标准并预测。
4. 结果报告：查看图表、结果、历史记录并下载报告。
5. 社区管理：查询、查看和维护社区完整信息。
6. 工程管理：新建、切换、备份和恢复工程。

它与原系统共用后端接口和 SQLite 数据库。原系统默认入口已采用此布局，不再显示初始工程选择页。

## 可选参数

| 参数 | 作用 |
| --- | --- |
| `projectId` | 进入指定工程 |
| `apiBase` | 指定后端接口地址 |
| `token` | 传入接口访问凭证 |
| `hostOrigin` | 限制宿主页面消息来源 |

生产环境建议使用同域反向代理或短期凭证，避免在公开链接中保存长期有效凭证。
