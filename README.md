# agt_finance_agent

AI driven purchase document intelligence and finance archive generator.

## Goal

Convert unordered raw inputs:

- invoice PDF
- product photos
- shopping order screenshots
- payment screenshots
- empty Excel templates

into structured purchase archives:

```
amount_date/
├── 01_item_name_amount.pdf
├── 实物图.docx
├── 购买凭证/
├── 支付凭证/
└── 采购统计.xlsx
```

## Design Principles

1. Core algorithm independent from UI/API/model providers.
2. Rule based processing for deterministic tasks (invoice parsing, amount calculation, export).
3. AI used for uncertain multimodal understanding (image classification, relationship inference).
4. Support many-to-many relationships:

```
Order
 ├── Items
 │    └── Invoices
 ├── Purchase Proof
 └── Payments
```

## Roadmap

### v0.1 Core pipeline

- file scanner
- document classifier
- invoice parser
- purchase graph model
- archive generator
- Excel/DOCX exporter

### v0.2 AI matching

- image embedding
- OCR assisted matching
- confidence scoring

### v0.3 Interfaces

- desktop UI
- REST API
- Agent/MCP integration

