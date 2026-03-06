# XHS WeChat Visual Report

基于公众号文章图片识别出的账号，采集小红书笔记后生成的静态可视化看板。

## 目录结构

- `index.html` `style.css` `app.js`: 静态页面
- `data/accounts.json`: 账号汇总
- `data/notes.json`: 全量笔记（按点赞排序）
- `data/stats.json`: 统计信息
- `data/raw_users/*.csv`: 每个账号的原始采集结果
- `data/wechat_images/*`: 公众号抓取图片

## 本地运行

```bash
python -m http.server 8000
```

浏览器打开 `http://localhost:8000/`。

## 重新生成数据

上游数据来自 `../xhs_collection_output/users/*.csv` 和 `../xhs_collection_output/wechat_images/*`：

```bash
python build_data.py
```

## 说明

- 页面为纯静态读取 JSON，不依赖数据库或后端服务。
- 采集行为请自行遵守目标平台的服务条款与适用法律法规。
