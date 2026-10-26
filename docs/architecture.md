# agt_finance_agent Architecture

## Data Flow

```
Raw Files
   |
   v
Scanner
   |
   v
Document Classification
   |
 +-----------+-------------+
 |           |             |
Invoice   Image        Payment
Parser    Analyzer     Parser
 |           |             |
 +-----------+-------------+
             |
             v
 Purchase Relation Graph
             |
             v
 DOCX + Excel + Archive Generator
```

## Relationship Model

A payment or shopping order can map to multiple items and invoices.
An invoice can contain multiple items.

The system must not assume:

```
invoice == item == order
```

## Output Rules

Archive directory (V0.1 and V0.2):

```
{total_amount}/
```

Contains:

- renamed invoice PDFs
- generated 实物图.docx
- one 实物图.docx containing product photos and purchase/payment proofs
- one 采购统计.xlsx with the established eight columns



## Guided V0.2

See [V0.2 implementation](v0_2_implementation.md) for managed batch state, confirmed relations, the unified ExportPlan, staged export and Windows validation.
