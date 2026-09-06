# AGT Finance Agent

面向采购/财务归档场景的文档智能整理工具。V0.1 已支持从一个无序采购资料文件夹中识别发票、实物照片和电商购买凭证，并通过人工复核 GUI 完成关系确认，最后生成一个标准化归档目录。

## V0.1 工作流

```text
选择原始资料文件夹
        ↓
PDF 发票解析 + 图片分类 + 购买凭证 OCR
        ↓
Purchase Relation Graph
        ↓
高置信自动匹配 + GUI 人工复核
        ↓
一致性检查
        ↓
最终归档
```

输入允许是不完整的任意子集，支付凭证不是强制项。确定性任务（发票字段、金额计算、归档）不依赖 LLM；视觉/语义能力只用于不确定关系的建议和辅助。

## 最终归档格式

一个采购批次只生成一个总金额文件夹：

```text
1918.79/
├── 01_无线下载调试器_237.00元.pdf
├── 02_焊接台_38.29元.pdf
├── ...
├── 15_DAP-LINK 仿真器_75.00元.pdf
├── 实物图.docx
└── 采购统计.xlsx
```

用户可见归档中不生成购买凭证/支付凭证子目录。购买凭证和可选支付凭证统一嵌入 `实物图.docx`。

## Windows V0.1

构建完成后运行：

```text
release/AGTFinanceAgent-v0.1.0/AGTFinanceAgent-v0.1.0.exe
```

双击 EXE 后：

1. 选择待整理采购资料文件夹。
2. 软件自动完成发票解析、图片分类、OCR 和关系恢复。
3. 自动进入“实物图人工复核”GUI。
4. 检查/修改照片与商品关系。
5. 点击“生成最终归档…”并选择输出位置。

详细说明见 `docs/V0.1_使用说明.md`。

## 开发环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[ocr]"
python -m pytest -q tests
```

构建 Windows V0.1：

```powershell
.\tools\build_windows_v0_1.ps1 -Python ".\.venv\Scripts\python.exe"
```

真实数据自动验收：

```powershell
python tools\run_v0_1_acceptance.py <输入目录> `
  --workspace-root <验收工作目录> `
  --expected-invoices 15 `
  --expected-images 30 `
  --expected-purchase-proofs 15
```

## 当前模块

- `core/parser`：PDF/表格/订单截图解析
- `core/document`：文档及图片分类
- `core/matcher`：购买凭证和实物图关系恢复
- `core/graph`：Purchase Graph 数据模型
- `core/review`：人工复核状态与 GUI
- `core/generators`：PDF/DOCX/XLSX 归档与一致性检查
- `core/vision`：可选视觉语义建议层
- `agt_finance_agent/app.py`：V0.1 Windows 桌面入口

## Roadmap

- V0.2：视觉语义模型、更多凭证类型、产品化配置与日志
- V0.3：FastAPI / MCP / Agent Tool 接口

