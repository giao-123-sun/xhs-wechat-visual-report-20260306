# XHS WeChat Visual Report

基于公众号文章图片识别出的账号，采集小红书笔记后生成的静态可视化看板，可直接部署到 GitHub Pages 阅读。

## 目录结构

- `index.html` `style.css` `app.js`: 静态页面
- `data/accounts.json`: 账号汇总
- `data/notes.json`: 全量笔记（按点赞排序）
- `data/stats.json`: 统计信息
- `data/raw_users/*.csv`: 每个账号的原始采集结果
- `data/wechat_images/*`: 公众号抓取图片
- `data/note_pipeline_summary.json`: 当前笔记处理进度 + 精选笔记卡片
- `data/note_pipeline/note_units.json`: 以笔记为单位的统一结构

## 页面内容

- 账号规模、分类分布、热门笔记
- 当前笔记处理进度（详情抓取 / OCR / 剩余待处理）
- 已处理笔记精选卡片：正文摘要 + 图片 OCR 摘要 + 封面图
- 公众号原始图片素材浏览

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

## 按笔记统一处理（内容 + 图片 + LLM OCR）

脚本：`process_notes_with_llm_ocr.py`

- `detail`：抓取每条笔记详情（标题、正文、互动数据、图片 URL）
- `download`：下载笔记图片到本地
- `ocr`：调用 OpenRouter 多模态模型做多图 OCR 并合并文本
- `merge`：合并为“以笔记为单位”的统一结构

示例：

```bash
# 1) 抓笔记详情（并发）
python process_notes_with_llm_ocr.py --stage detail --detail-workers 8 --no-download

# 2) 下载图片（并发）
python process_notes_with_llm_ocr.py --stage download --download-workers 12

# 3) LLM OCR（需要 OpenRouter key）
export OPENROUTER_API_KEY=YOUR_KEY
python process_notes_with_llm_ocr.py --stage ocr --ocr-workers 3 --model google/gemini-2.5-flash-lite

# 4) 合并最终笔记单元
python process_notes_with_llm_ocr.py --stage merge
```

输出位置：

- `data/note_pipeline/note_units.json`（统一笔记单元）
- `data/note_pipeline/note_units.jsonl`
- `data/note_pipeline/note_images/*`

## 说明

- 页面为纯静态读取 JSON，不依赖数据库或后端服务。
- 当前 GitHub Pages 会优先呈现已完成处理的内容，不等待全量流水线结束。
- 采集行为请自行遵守目标平台的服务条款与适用法律法规。
