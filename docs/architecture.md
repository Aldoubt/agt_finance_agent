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

Archive directory:

```
{total_amount}_{date}/
```

Contains:

- renamed invoice PDFs
- generated 实物图.docx
- purchase proof images
- payment proof images
- Excel summary
