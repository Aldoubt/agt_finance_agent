# AGT Finance Agent · 采购报销材料整理

把邮箱下载的发票、收货照片和淘宝订单截图整理成一个可核对的报销材料文件夹。

## Windows V0.2 交互预览

[下载 Windows 预览包](https://github.com/Aldoubt/agt_finance_agent/releases) · [首次使用说明](docs/V0.2_使用说明.md)

解压完整压缩包，双击 **开始整理.bat** 或 **AGTFinanceAgent.exe**。保留旁边的 `_internal` 文件夹。
第一次可点“查看示例”，用独立的虚构材料体验完整流程；再点“开始整理”添加自己的材料。

**放入材料 → 核对清单 → 确认照片 → 预览导出**

- 文件名乱码、数字或未命名都可以，不用提前重命名。
- 照片先到、发票后补也能保存；首页可以继续上次整理。
- 发票字段和商品可人工修改，照片/订单/支付凭证可关联多个商品。
- 只有快递外箱时明确提示补拍商品，外包装不计为商品实物图。
- 材料复制到本机批次工作区，确认后保存；重复导入不重复计费。
- 人工确认的发票顺序统一用于 PDF、Word 和 Excel。
- 导出先检查金额与文件，再完整生成；同金额目录不会混入旧文件。

### 保持原来的输出格式

总金额目录内只包含顺序命名的发票 PDF、`实物图.docx`、`采购统计.xlsx`。
Excel 仍是八列：序号、商品名称、金额、发票是否存在、实物图是否存在、购买凭证是否存在、支付凭证是否存在、发票文件；底部保留总金额。
购买/支付凭证在 Word 内，支付凭证继续为选填项。

### 开发与构建

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[ocr,build,test]"
python -m pytest -q tests
python -m agt_finance_agent.app --demo
.\tools\build_windows_v0_2.ps1 -Python ".\.venv\Scripts\python.exe"
```

默认启动 V0.2 向导。`--legacy-review` 可打开旧版照片复核，`--analysis-only --input-dir <目录>` 保留旧版批处理入口。
[实现与验证说明](docs/v0_2_implementation.md)。预览版使用合成材料完成自动验证，真实票据和 Windows 人工交互仍需试用。

---

## V0.1 历史说明

以下保留旧版工作流与验收样本记录，V0.2 使用上面的新入口。

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
